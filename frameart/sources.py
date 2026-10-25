"""Where the pictures come from. Each source lists keys (cheap to keep) and fetches one key as a picture.

keys() may be slow (it searches); the service keeps the list for a day. fetch() returns (PIL image, label), or
raises Skip when that key can never be used (not public domain, no image, the wrong shape), so it's not tried again.
"""
import html
import json
import logging
import os
import re

from . import image, net

log = logging.getLogger(__name__)


class Skip(Exception):
    pass


def _years(text):
    """'1800-1920' -> (1800, 1920); '' -> None."""
    m = re.match(r"^\s*(-?\d+)\s*-\s*(-?\d+)\s*$", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


class Folder:
    """Pictures in a folder (and its subfolders). Any shape goes: what isn't close to 16:9 is shown whole."""
    name = "folder"
    pool_hours = 0  # cheap: look again every time
    EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff")

    def __init__(self, path):
        self.path = path

    def keys(self):
        if not os.path.isdir(self.path):
            log.warning("folder %s doesn't exist", self.path)
            return []
        out = []
        for root, dirs, files in os.walk(self.path):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                if f.lower().endswith(self.EXT) and not f.startswith("."):
                    out.append(os.path.relpath(os.path.join(root, f), self.path))
        return sorted(out)

    def fetch(self, key):
        with open(os.path.join(self.path, key), "rb") as f:
            try:
                img = image.open_image(f.read())
            except Exception as e:
                raise Skip("not a picture Pillow reads: %s" % e)
        return img, key


class Met:
    """The Metropolitan Museum of Art: public-domain paintings found by the search words."""
    name = "met"
    pool_hours = 24
    API = "https://collectionapi.metmuseum.org/public/collection/"  # search is v1.1 since 1.10.2026, objects still v1

    def __init__(self, queries, years=""):
        self.queries = queries or ["landscape"]
        self.years = _years(years)

    def keys(self):
        ids = []
        for q in self.queries:
            params = {"q": q, "hasImages": "true", "isPublicDomain": "true", "medium": "Paintings", "limit": 100}
            if self.years:
                params.update(dateBegin=self.years[0], dateEnd=self.years[1])
            for offset in range(0, 500, 100):
                r = net.get_json(self.API + "v1.1/search", dict(params, offset=offset))
                ids += r.get("objectIDs") or []
                if offset + 100 >= (r.get("total") or 0):
                    break
        return [str(i) for i in dict.fromkeys(ids)]

    def fetch(self, key):
        o = net.get_json(self.API + "v1/objects/" + key)
        if not o.get("isPublicDomain") or not o.get("primaryImage"):
            raise Skip("not public domain or no image")
        if o.get("classification") != "Paintings":
            raise Skip("a %s, not a painting" % (o.get("classification") or "something"))
        if o.get("primaryImageSmall"):  # the shape from the small copy before the original, which can be 50 MB
            small = image.open_image(net.get(o["primaryImageSmall"]))
            if not image.croppable(*small.size):
                raise Skip("%dx%d isn't close to 16:9" % small.size)
        img = image.open_image(net.get(o["primaryImage"], timeout=180))
        if not image.big_enough(*img.size):
            raise Skip("%dx%d is too small or not close to 16:9" % img.size)
        return img, "%s, %s (%s)" % (o.get("title"), o.get("artistDisplayName") or "unknown", o.get("objectDate"))


class Rijksmuseum:
    """Rijksmuseum: paintings with an image (they're public domain), through its Linked Art search and IIIF.

    A query is free text for the description ("zee"), or the search's own fields ("creator=Vermeer").
    """
    name = "rijksmuseum"
    pool_hours = 24
    SEARCH = "https://data.rijksmuseum.nl/search/collection"
    LD = "application/ld+json"

    def __init__(self, queries, years=""):
        self.queries = queries or ["landscape"]
        self.years = _years(years)

    def keys(self):
        ids = []
        for q in self.queries:
            params = dict(p.split("=", 1) for p in q.split("&")) if "=" in q else {"description": q}
            params.setdefault("type", "painting")
            params["imageAvailable"] = "true"
            url = self.SEARCH
            for _ in range(5):  # 100 a page
                r = net.get_json(url, params, self.LD)
                ids += [i["id"] for i in r.get("orderedItems", [])]
                url, params = (r.get("next") or {}).get("id"), None
                if not url:
                    break
        return list(dict.fromkeys(ids))

    def fetch(self, key):
        raw = net.get(key, accept=self.LD)
        if b"creativecommons.org/publicdomain/" not in raw:
            raise Skip("not marked public domain")
        o = json.loads(raw)
        span = (o.get("produced_by") or {}).get("timespan") or {}
        year = int((span.get("begin_of_the_begin") or "0")[:4] or 0)
        if self.years and not self.years[0] <= year <= self.years[1]:
            raise Skip("from %d" % year)
        try:
            visual = net.get_json(o["shows"][0]["id"], accept=self.LD)
            digital = net.get_json(visual["digitally_shown_by"][0]["id"], accept=self.LD)
            iiif = digital["access_point"][0]["id"].split("/full/")[0]
        except (KeyError, IndexError):
            raise Skip("no image")
        info = net.get_json(iiif + "/info.json")
        if not image.big_enough(info["width"], info["height"]):
            raise Skip("%dx%d is too small or not close to 16:9" % (info["width"], info["height"]))
        img = image.open_image(net.get(iiif + "/full/!4000,4000/0/default.jpg", timeout=180))
        return img, "%s (%s)" % (_rijks_title(o), year)


def _rijks_title(o):
    names = [n for n in o.get("identified_by", []) if n.get("type") == "Name"]
    english = [n for n in names if "300388277" in str(n.get("language"))]  # AAT: English
    return (english or names or [{"content": "?"}])[0]["content"]


class Commons:
    """Wikimedia Commons categories. The default is Nasjonalmuseet's paintings, a category per artist; an entry is
    an artist ("Hans Gude") or a whole category ("Category:...")."""
    name = "nasjonalmuseet"
    pool_hours = 24
    API = "https://commons.wikimedia.org/w/api.php"
    NM = "Category:Paintings by %s in the Nasjonalmuseet for kunst, arkitektur og design"
    FREE = ("public domain", "pd", "cc0", "cc-zero")

    def __init__(self, entries):
        self.categories = [e if e.startswith("Category:") else self.NM % e for e in entries]

    def keys(self):
        keys = []
        for cat in self.categories:
            params = {"action": "query", "format": "json", "generator": "categorymembers", "gcmtitle": cat,
                      "gcmtype": "file", "gcmlimit": 500, "prop": "imageinfo", "iiprop": "size"}
            found = 0
            while True:
                r = net.get_json(self.API, params)
                for p in (r.get("query") or {}).get("pages", {}).values():
                    info = (p.get("imageinfo") or [{}])[0]
                    found += 1
                    if image.big_enough(info.get("width", 0), info.get("height", 0)):
                        keys.append(p["title"])
                if "continue" not in r:
                    break
                params.update(r["continue"])
            if not found:
                log.warning("nothing in %s (is the name right?)", cat)
        return list(dict.fromkeys(keys))

    def fetch(self, key):
        r = net.get_json(self.API, {"action": "query", "format": "json", "titles": key, "prop": "imageinfo",
                                    "iiprop": "url|size|extmetadata", "iiurlwidth": 3840,
                                    "iiextmetadatafilter": "LicenseShortName"})
        page = list(r["query"]["pages"].values())[0]
        info = (page.get("imageinfo") or [None])[0]
        if not info:
            raise Skip("gone")
        lic = html.unescape(info.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "")).lower()
        if not any(lic.startswith(f) for f in self.FREE):
            raise Skip("licence %r" % lic)
        # thumburl is the 3840-wide copy, or the original when that's smaller
        img = image.open_image(net.get(info.get("thumburl") or info["url"], timeout=180))
        return img, _commons_label(key)


def _commons_label(title):
    # "File:Hans Gude - Fra Hardanger - NG.M.00170 - National Museum of Art, Architecture and Design.jpg"
    parts = os.path.splitext(title[5:])[0].split(" - ")
    return "%s, %s" % (parts[1], parts[0]) if len(parts) > 2 else parts[0]


def from_config(cfg):
    out = []
    if cfg.get("folder"):
        out.append(Folder(cfg.get("folder_path") or "/media/frame-art"))
    if cfg.get("museums"):
        years = cfg.get("years", "")
        if cfg.get("met", True):
            out.append(Met(cfg.get("met_queries"), years))
        if cfg.get("rijksmuseum", True):
            out.append(Rijksmuseum(cfg.get("rijksmuseum_queries"), years))
        if cfg.get("nasjonalmuseet", True):
            out.append(Commons(cfg.get("nasjonalmuseet_artists") or DEFAULT_ARTISTS))
    return out


DEFAULT_ARTISTS = ["Hans Gude", "Harald Sohlberg", "Edvard Munch", "Nikolai Astrup", "Theodor Kittelsen"]
