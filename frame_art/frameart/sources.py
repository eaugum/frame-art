"""Where the pictures come from. Each source lists keys (cheap to keep) and fetches one key as a picture.

The sources are a list in the options, each with a type and a query (see TYPES and DOCS.md), so a new one is a few
lines in Home Assistant. keys() may be slow (it searches); the service keeps the list for a day. fetch() returns
(PIL image, label), or raises Skip when that key can never be used (not free, no image, the wrong shape), so it's not
tried again. thumb() is a small copy for the add-on's page, as a URL to fetch or the picture itself.

A source belongs to a category (the field category, else its own name); several sources can share one.
"""
import json
import logging
import os
import random
import re
import time
import urllib.parse

from . import image, net

log = logging.getLogger(__name__)


class Skip(Exception):
    pass


def _fields(query, key):
    """'zee' -> {key: 'zee'}; the search's own fields as 'medium=Prints&q=Hokusai' -> as they are."""
    if "=" not in query:
        return {key: query}
    return dict(p.split("=", 1) for p in query.split("&") if "=" in p)


def _text(html_text, limit=80):
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_text or "")).strip()
    text = re.sub(r"\s*\b(label|title) QS:.*$", "", text)  # Wikidata templates Commons leaves in ("label QS:Len,...")
    return text if len(text) <= limit else ""


class Source:
    """An entry in the options: name, type, query (several with |) and category; every source in the list is on. Only
    pictures close to 16:9 are used, cropped to fill the screen."""
    type = None
    pool_hours = 24
    default = []

    def __init__(self, entry, cfg):
        self.name = entry["name"]
        self.queries = [q.strip() for q in (entry.get("query") or "").split("|") if q.strip()] or self.default
        self.category = re.sub(r"\s+", " ", str(entry.get("category") or "")).strip() or self.name

    def usable(self, width, height):
        return image.big_enough(width, height)

    def check(self, width, height):
        if not self.usable(width, height):
            raise Skip("%dx%d is too small or not close to 16:9" % (width, height))

    def thumb(self, key):
        """A small copy: a URL, or a PIL image. Without one of its own, the whole picture (slow)."""
        return self.fetch(key)[0]


class Folder(Source):
    """Pictures in a folder (and its subfolders); the query is the path. One that isn't close to 16:9 is skipped when
    it's drawn."""
    type = "folder"
    pool_hours = 0  # cheap: look again every time
    EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff")

    def __init__(self, entry, cfg):
        Source.__init__(self, entry, cfg)
        self.path = self.queries[0] if self.queries else "/media/frame-art"

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

    def thumb(self, key):
        with open(os.path.join(self.path, key), "rb") as f:
            img = image.open_image(f.read(), draft=image.THUMB)
        return img


class Met(Source):
    """The Metropolitan Museum of Art, public domain. The query is search words, or the search's fields
    ("medium=Prints&q=Hiroshige"); without a medium, paintings."""
    type = "met"
    default = ["landscape"]
    API = "https://collectionapi.metmuseum.org/public/collection/"  # search is v1.1 since 1.10.2026, objects still v1

    def keys(self):
        ids = []
        for q in self.queries:
            params = {"hasImages": "true", "isPublicDomain": "true", "medium": "Paintings", "limit": 100}
            params.update(_fields(q, "q"))
            for offset in range(0, 500, 100):
                r = net.get_json(self.API + "v1.1/search", dict(params, offset=offset))
                ids += r.get("objectIDs") or []
                if offset + 100 >= (r.get("total") or 0):
                    break
        return [str(i) for i in dict.fromkeys(ids)]

    def paintings_only(self):
        return all(_fields(q, "q").get("medium", "Paintings") == "Paintings" for q in self.queries)

    def fetch(self, key):
        o = net.get_json(self.API + "v1/objects/" + key)
        if not o.get("isPublicDomain") or not o.get("primaryImage"):
            raise Skip("not public domain or no image")
        if self.paintings_only() and o.get("classification") != "Paintings":
            raise Skip("a %s, not a painting" % (o.get("classification") or "something"))
        if o.get("primaryImageSmall"):  # the shape from the small copy; the original can be 50 MB
            small = image.open_image(net.get(o["primaryImageSmall"]))
            if not image.croppable(*small.size):
                raise Skip("%dx%d isn't close to 16:9" % small.size)
        img = image.open_image(net.get(o["primaryImage"], timeout=180))
        self.check(*img.size)
        return img, "%s, %s (%s)" % (o.get("title"), o.get("artistDisplayName") or "unknown", o.get("objectDate"))

    def thumb(self, key):
        o = net.get_json(self.API + "v1/objects/" + key)
        if not o.get("primaryImageSmall"):
            raise Skip("no image")
        return o["primaryImageSmall"]


class Rijksmuseum(Source):
    """Rijksmuseum: works with an image (they're public domain), through its Linked Art search and IIIF.

    A query is free text for the description ("zee"), or the search's own fields ("creator=Vermeer"); without a
    type, paintings.
    """
    type = "rijksmuseum"
    default = ["landschap"]
    SEARCH = "https://data.rijksmuseum.nl/search/collection"
    LD = "application/ld+json"

    def keys(self):
        ids = []
        for q in self.queries:
            params = _fields(q, "description")
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
        year = (span.get("begin_of_the_begin") or "")[:4].lstrip("0")
        iiif = self.iiif(o)
        info = net.get_json(iiif + "/info.json")
        self.check(info["width"], info["height"])
        img = image.open_image(net.get(iiif + "/full/!4000,4000/0/default.jpg", timeout=180))
        title = _rijks_title(o)
        return img, "%s (%s)" % (title, year) if year else title

    def iiif(self, o):
        try:
            visual = net.get_json(o["shows"][0]["id"], accept=self.LD)
            digital = net.get_json(visual["digitally_shown_by"][0]["id"], accept=self.LD)
            return digital["access_point"][0]["id"].split("/full/")[0]
        except (KeyError, IndexError):
            raise Skip("no image")

    def thumb(self, key):
        return self.iiif(net.get_json(key, accept=self.LD)) + "/full/!%d,%d/0/default.jpg" % (image.THUMB, image.THUMB)


def _rijks_title(o):
    names = [n for n in o.get("identified_by", []) if n.get("type") == "Name"]
    english = [n for n in names if "300388277" in str(n.get("language"))]  # AAT: English
    return (english or names or [{"content": "?"}])[0]["content"]


class Commons(Source):
    """Wikimedia Commons categories ("Paintings by Hilma af Klint", "Category:" may be left out), with their
    subcategories two levels down. Everything on Commons is free to use."""
    type = "commons"
    API = "https://commons.wikimedia.org/w/api.php"
    SUBCATEGORIES = 2  # "Paintings by Claude Monet" has hardly a file of its own, all by year and museum
    MAX_CATEGORIES = 150  # per query, so a huge tree doesn't take an hour
    PAUSE = 0.5  # seconds between requests: Wikimedia answers 429 to a bot in a hurry

    def top(self, query):
        return query if query.startswith("Category:") else "Category:" + query

    def keys(self):
        keys = []
        for q in self.queries:
            found, seen, level = 0, set(), [self.top(q)]
            for depth in range(self.SUBCATEGORIES + 1):
                below = []
                for cat in level:
                    if len(seen) >= self.MAX_CATEGORIES:
                        break
                    seen.add(cat)
                    params = {"action": "query", "format": "json", "generator": "categorymembers", "gcmtitle": cat,
                              "gcmtype": "file|subcat" if depth < self.SUBCATEGORIES else "file", "gcmlimit": 500,
                              "prop": "imageinfo", "iiprop": "size"}
                    while True:  # files and subcategories in one go
                        time.sleep(self.PAUSE)
                        r = net.get_json(self.API, params)
                        for p in (r.get("query") or {}).get("pages", {}).values():
                            if p.get("ns") == 14:
                                below.append(p["title"])
                                continue
                            info = (p.get("imageinfo") or [{}])[0]
                            found += 1
                            if self.usable(info.get("width", 0), info.get("height", 0)):
                                keys.append(p["title"])
                        if "continue" not in r:
                            break
                        params.update(r["continue"])
                level = [c for c in dict.fromkeys(below) if c not in seen]
            if not found:
                log.warning("%s: nothing in %s (is the name right?)", self.name, q)
        return list(dict.fromkeys(keys))

    def fetch(self, key):
        r = net.get_json(self.API, {"action": "query", "format": "json", "titles": key, "prop": "imageinfo",
                                    "iiprop": "url|size|extmetadata", "iiurlwidth": 3840,
                                    "iiextmetadatafilter": "ObjectName|Artist|DateTimeOriginal"})
        page = list(r["query"]["pages"].values())[0]
        info = (page.get("imageinfo") or [None])[0]
        if not info:
            raise Skip("gone")
        # thumburl is the 3840-wide copy, or the original when that's smaller
        img = image.open_image(net.get(info.get("thumburl") or info["url"], timeout=180))
        return img, self.label(key, info.get("extmetadata") or {})

    def thumb(self, key):
        r = net.get_json(self.API, {"action": "query", "format": "json", "titles": key, "prop": "imageinfo",
                                    "iiprop": "url", "iiurlwidth": image.THUMB})
        info = (list(r["query"]["pages"].values())[0].get("imageinfo") or [None])[0]
        if not info:
            raise Skip("gone")
        return info.get("thumburl") or info["url"]

    def label(self, key, meta):
        title, artist, date = (_text((meta.get(k) or {}).get("value")) for k in ("ObjectName", "Artist",
                                                                                   "DateTimeOriginal"))
        if not title:
            return _commons_label(key)
        year = re.search(r"\d{4}", date)  # often a Wikidata template ("1933 date QS:P571,+1")
        return title + (", " + artist if artist else "") + (" (%s)" % year.group() if year else "")


class Nasjonalmuseet(Commons):
    """Nasjonalmuseet's paintings on Commons, a category per artist ("Hans Gude")."""
    type = "nasjonalmuseet"
    default = ["Hans Gude", "Harald Sohlberg", "Edvard Munch", "Nikolai Astrup", "Theodor Kittelsen"]
    NM = "Category:Paintings by %s in the Nasjonalmuseet for kunst, arkitektur og design"

    SUBCATEGORIES = 0

    def top(self, query):
        return query if query.startswith("Category:") else self.NM % query

    def label(self, key, meta):
        return _commons_label(key)


def _commons_label(title):
    # "File:Hans Gude - Fra Hardanger - NG.M.00170 - National Museum of Art, Architecture and Design.jpg"
    parts = os.path.splitext(title[5:])[0].split(" - ")
    return "%s, %s" % (parts[1], parts[0]) if len(parts) > 2 else parts[0]


class Cleveland(Source):
    """The Cleveland Museum of Art, CC0. The query is search words, or the API's fields ("type=Print&q=Hokusai");
    without a type, paintings."""
    type = "cleveland"
    default = ["landscape"]
    API = "https://openaccess-api.clevelandart.org/api/artworks/"

    def keys(self):
        keys = []
        for q in self.queries:
            params = {"type": "Painting", "has_image": 1, "cc0": 1, "limit": 100, "fields": "id,images"}
            params.update(_fields(q, "q"))
            for skip in range(0, 1000, 100):
                r = net.get_json(self.API, dict(params, skip=skip))
                for o in r.get("data") or []:
                    im = (o.get("images") or {}).get("print") or {}
                    if self.usable(int(im.get("width") or 0), int(im.get("height") or 0)):
                        keys.append(str(o["id"]))
                if skip + 100 >= ((r.get("info") or {}).get("total") or 0):
                    break
        return list(dict.fromkeys(keys))

    def fetch(self, key):
        o = net.get_json(self.API + key)["data"]
        im = ((o.get("images") or {}).get("print") or {})
        if o.get("share_license_status") != "CC0" or not im.get("url"):
            raise Skip("not CC0 or no image")
        img = image.open_image(net.get(im["url"], timeout=180))
        self.check(*img.size)
        artist = ((o.get("creators") or [{}])[0].get("description") or "unknown").split(" (")[0]
        return img, "%s, %s (%s)" % (o.get("title"), artist, o.get("creation_date"))

    def thumb(self, key):
        url = ((net.get_json(self.API + key)["data"].get("images") or {}).get("web") or {}).get("url")
        if not url:
            raise Skip("no image")
        return url


class SMK(Source):
    """Statens Museum for Kunst in Copenhagen, public domain. The query is search words ("landskab"), or "*" for
    everything; its filters go in as fields ("keys=*&object_names=tegning"). Without object_names, paintings."""
    type = "smk"
    default = ["*"]
    API = "https://api.smk.dk/api/v1/art/"

    def keys(self):
        keys = []
        for q in self.queries:
            fields = _fields(q, "keys")
            filters = {"has_image": "true", "public_domain": "true", "object_names": "maleri"}
            filters.update((k, v) for k, v in fields.items() if k != "keys")
            params = {"keys": fields.get("keys", "*"), "rows": 100,
                      "filters": ",".join("[%s:%s]" % kv for kv in filters.items()),
                      "fields": "object_number,image_width,image_height,image_iiif_id,production_date"}
            for offset in range(0, 2000, 100):
                r = net.get_json(self.API + "search/", dict(params, offset=offset))
                for o in r.get("items") or []:
                    if o.get("image_iiif_id") and \
                            self.usable(o.get("image_width") or 0, o.get("image_height") or 0):
                        keys.append(o["object_number"])
                if offset + 100 >= (r.get("found") or 0):
                    break
        return list(dict.fromkeys(keys))

    def fetch(self, key):
        items = net.get_json(self.API, {"object_number": key}).get("items") or []
        if not items or not items[0].get("image_iiif_id") or not items[0].get("public_domain", True):
            raise Skip("gone or not public domain")
        o = items[0]
        img = image.open_image(net.get(o["image_iiif_id"] + "/full/!3840,3840/0/default.jpg", timeout=180))
        title = ((o.get("titles") or [{}])[0].get("title")) or "?"
        period = ((o.get("production_date") or [{}])[0].get("period")) or ""
        return img, "%s, %s (%s)" % (title, ", ".join(o.get("artist") or ["unknown"]), period)

    def thumb(self, key):
        items = net.get_json(self.API, {"object_number": key}).get("items") or []
        if not items or not items[0].get("image_iiif_id"):
            raise Skip("gone")
        return items[0]["image_iiif_id"] + "/full/!%d,%d/0/default.jpg" % (image.THUMB, image.THUMB)


class NASA(Source):
    """NASA's Image and Video Library: search words ("nebula", "earth from space"). NASA's own pictures are free.
    Many are square, and only the wide ones are used."""
    type = "nasa"
    default = ["nebula"]
    API = "https://images-api.nasa.gov/"

    def keys(self):
        ids = []
        for q in self.queries:
            params = {"media_type": "image", "page_size": 100}
            params.update(_fields(q, "q"))
            for page in range(1, 6):
                items = net.get_json(self.API + "search", dict(params, page=page))["collection"]["items"]
                ids += [i["data"][0]["nasa_id"] for i in items if i.get("data")]
                if len(items) < 100:
                    break
        return list(dict.fromkeys(ids))

    def fetch(self, key):
        files = net.get_json(self.API + "asset/" + key)["collection"]["items"]
        urls = [f["href"].replace("http://", "https://") for f in files]
        url = next((u for u in urls if u.endswith("~orig.jpg")), None) or \
            next((u for u in urls if u.endswith("~large.jpg")), None)
        if not url:
            raise Skip("no JPEG")
        img = image.open_image(net.get(url, timeout=180))
        self.check(*img.size)
        data = (net.get_json(self.API + "search", {"nasa_id": key})["collection"]["items"] or [{"data": [{}]}])
        d = data[0]["data"][0]
        return img, "%s (%s)" % (d.get("title") or key, (d.get("date_created") or "")[:4])

    def thumb(self, key):
        return "https://images-assets.nasa.gov/image/%s/%s~thumb.jpg" % (urllib.parse.quote(key), urllib.parse.quote(key))


class Wellcome(Source):
    """Wellcome Collection: search words ("botanical", "anatomy", "astronomy"), public domain and CC0 only. Mostly
    old illustrations of every shape, and only the wide ones are used."""
    type = "wellcome"
    default = ["botanical"]
    API = "https://api.wellcomecollection.org/catalogue/v2/images"

    def keys(self):
        ids = []
        for q in self.queries:
            params = {"locations.license": "pdm,cc-0", "pageSize": 100}
            params.update(_fields(q, "query"))
            for page in range(1, 6):
                r = net.get_json(self.API, dict(params, page=page))
                for o in r.get("results") or []:
                    ratio = o.get("aspectRatio") or 0
                    if image.croppable(ratio, 1):
                        ids.append(o["id"])
                if page >= (r.get("totalPages") or 0):
                    break
        return list(dict.fromkeys(ids))

    def fetch(self, key):
        o = net.get_json(self.API + "/" + key)
        iiif = next((l["url"] for l in o.get("locations") or [] if l.get("url", "").endswith("/info.json")), None)
        if not iiif:
            raise Skip("no IIIF image")
        info = net.get_json(iiif)
        self.check(info["width"], info["height"])
        img = image.open_image(net.get(iiif[:-len("/info.json")] + "/full/!3840,3840/0/default.jpg", timeout=180))
        return img, (o.get("source") or {}).get("title") or key

    def thumb(self, key):
        o = net.get_json(self.API + "/" + key)
        iiif = next((l["url"] for l in o.get("locations") or [] if l.get("url", "").endswith("/info.json")), None)
        if not iiif:
            raise Skip("no IIIF image")
        return iiif[:-len("/info.json")] + "/full/!%d,%d/0/default.jpg" % (image.THUMB, image.THUMB)


class Stasera(Source):
    """Backdrops of what we watch, from Stasera: watching, wantToStart, movies, recommendations. The add-on has to be
    linked to Stasera; no TMDB key, since the pictures are on TMDB's open image server."""
    type = "stasera"
    pool_hours = 6  # the lists change as we watch
    default = ["watching", "movies"]
    LISTS = ("watching", "wantToStart", "movies", "recommendations")
    IMAGES = "https://image.tmdb.org/t/p/"

    def __init__(self, entry, cfg):
        Source.__init__(self, entry, cfg)
        self.client = None  # the add-on's Stasera, set by from_config
        self.titles = {}

    def keys(self):
        lists = [q for q in self.queries if q in self.LISTS]
        for q in self.queries:
            if q not in self.LISTS:
                log.warning("%s: Stasera has no list called %s (%s)", self.name, q, ", ".join(self.LISTS))
        if not self.client or not self.client.on:
            log.warning("%s: no stasera_url in the options", self.name)
            return []
        self.titles = {}
        for t in self.client.titles(lists):
            path = t.get("textlessBackdropPath") or t.get("backdropPath")
            if path:
                self.titles.setdefault("%s:%s" % (t.get("kind"), t.get("tmdbId")), dict(t, path=path))
        return list(self.titles)

    def title(self, key):
        if key not in self.titles:
            self.keys()  # after a restart, or it's new
        t = self.titles.get(key)
        if not t:
            raise RuntimeError("%s isn't in Stasera's lists now" % key)  # not Skip: it may come back
        return t

    def fetch(self, key):
        t = self.title(key)
        img = image.open_image(net.get(self.IMAGES + "original" + t["path"], timeout=180))
        self.check(*img.size)
        return img, "%s (%s)" % (t.get("title") or "?", t.get("year") or "")

    def thumb(self, key):
        return self.IMAGES + "w500" + self.title(key)["path"]


TYPES = {c.type: c for c in (Folder, Met, Rijksmuseum, Commons, Nasjonalmuseet, Cleveland, SMK, NASA, Wellcome,
                             Stasera)}


def from_config(cfg, stasera=None):
    entries = cfg["sources"] if "sources" in cfg else _old_options(cfg)
    out = []
    for e in entries:
        cls = TYPES.get(e.get("type"))
        if not cls:
            log.warning("unknown source type %r (one of %s)", e.get("type"), ", ".join(TYPES))
            continue
        name = re.sub(r"\s+", " ", (e.get("name") or e["type"]).replace(":", " ")).strip()  # ": " ends the name
        if name in [s.name for s in out]:
            name += " %d" % (len(out) + 1)
        src = cls(dict(e, name=name), cfg)
        if cls is Stasera:
            src.client = stasera
        out.append(src)
    return out


def _old_options(cfg):
    """The options before the list (0.3): folder, museums and a switch and words for each museum."""
    out = []
    if cfg.get("folder"):
        out.append({"name": "folder", "type": "folder", "query": cfg.get("folder_path") or ""})
    if cfg.get("museums"):
        for t, words in (("met", "met_queries"), ("rijksmuseum", "rijksmuseum_queries"),
                         ("nasjonalmuseet", "nasjonalmuseet_artists")):
            if cfg.get(t, True):
                out.append({"name": t, "type": t, "query": "|".join(cfg.get(words) or [])})
    return out
