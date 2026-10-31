"""Where the pictures come from. Each source lists keys (cheap to keep) and fetches one key as a picture.

The sources are a list in the options, each with a type and a query. The type is a folder, or a service described in
the options too (see DOCS.md): no service is in the code, so everything can be replaced or removed there. keys() may be slow (it searches); the service keeps the list for a day. fetch() returns
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
import urllib.error
import urllib.parse

from . import image, net
from .stasera import Unlinked

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


def _at(o, path):
    """'images.0.url' in an answer, None when it isn't there; an empty path is the answer itself. '?text' in a path is
    the first in a list with that text in it."""
    for part in path.split(".") if path else []:
        if isinstance(o, list) and part.startswith("?"):
            o = next((x for x in o if part[1:] in json.dumps(x)), None)
        elif isinstance(o, list) and part.isdigit() and int(part) < len(o):
            o = o[int(part)]
        elif isinstance(o, dict) and part in o:
            o = o[part]
        else:
            return None
    return o


def _each(o, path):
    """The list at a path; 'items.*.backdrops' is every item's backdrops, each with its item's fields."""
    head, star, rest = path.partition(".*")
    if not star:
        return _at(o, path)
    out = []
    for parent in _at(o, head) or []:
        for child in _each(parent, rest.lstrip(".")) or []:
            out.append(dict(parent, **child) if isinstance(child, dict) else child)
    return out


def _filter(value, name):
    """One step after | in braces: {date|year}, {url|before:/full/}, {id|file|part:1}. None: there's no such part."""
    name, _, arg = name.partition(":")
    if name == "before":
        return value.split(arg)[0]
    if name == "year":
        year = re.search(r"\d{4}", value)
        return year.group() if year else None
    if name == "file":
        return os.path.splitext(value.split(":", 1)[-1])[0]
    if name == "part":
        parts = value.split(" - ")
        return parts[int(arg)] if int(arg) < len(parts) else None
    raise ValueError("no filter called %s" % name)


def _value(expression, context):
    path, *filters = expression.split("|")
    value = _at(context, path)
    if isinstance(value, (dict, list, type(None))) or value == "":
        return None
    value = str(value)
    for f in filters:
        value = _filter(value, f) if value else None
    return value


def _fill(spec, context, url=False):
    """A path, or a text with paths in braces; alternatives with " | ", and the first that has all it needs counts.
    In a URL a value is encoded, except one that starts the URL: that's an address itself."""
    for text in re.split(r"\s+\|\s+", spec or ""):
        if "{" not in text:
            value = _value(text, context)
            if value:
                return value
            continue
        missing = []

        def field(m):
            value = _value(m.group(1), context)
            if value is None:
                missing.append(m.group(1))
                return ""
            return urllib.parse.quote(value, safe="/:") if url and m.start() else value

        out = re.sub(r"\{([^{}]+)\}", field, text)
        if not missing:
            return out
    return None


def _search(url, query):
    """The search for one query: words go in {query}; fields ("medium=Prints&q=Hokusai") replace the url's own."""
    if "=" not in query:
        return url.replace("{query}", urllib.parse.quote(query, safe=""))
    fields = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
    base, _, params = url.partition("?")
    kept = [p for p in params.split("&") if p and "{query}" not in p and p.split("=")[0] not in fields]
    return base + "?" + "&".join(kept + ["%s=%s" % (k, urllib.parse.quote(v, safe="")) for k, v in fields.items()])


class Web(Source):
    """A service described in the options, so no service is in the code. Fields are in DOCS.md: url, items and id
    list the keys; steps are the calls per picture, and their answers are {step1}, {step2}...; image, title, thumb,
    width, height and ratio are read from the list's item and the steps. A key is all that's kept, so what's needed
    after a restart comes from steps, or from reading the list again."""
    type = "json"
    PAGES = 5
    WAIT = 90  # seconds for a service to finish what it says is pending
    MISSING = (403, 404, 410)  # this picture isn't there for us, and won't be

    def __init__(self, entry, cfg):
        Source.__init__(self, entry, cfg)
        self.spec = entry
        self.pool_hours = entry.get("hours", 24)
        self.stasera = "{stasera}" in entry.get("url", "")
        self.client = None  # the add-on's Stasera, set by from_config
        self.items = {}

    def ask(self, url):
        if self.stasera:
            return self.client.ask(url)
        return net.get_json(url, accept=self.spec.get("accept") or "application/json")

    def link(self, spec, context):
        """An absolute http(s) URL, or None: what an answer says isn't ours to open as a file."""
        url = _fill(spec, context, True)
        return url if url and url.startswith(("http://", "https://")) else None

    def answer(self, url):
        """The answer to a search, when the service has finished with it."""
        got, deadline = self.ask(url), time.time() + self.WAIT
        while self.spec.get("wait") and _at(got, self.spec["wait"]) and time.time() < deadline:
            time.sleep(10)
            got = self.ask(url)
        if self.spec.get("wait") and _at(got, self.spec["wait"]):  # not Skip: asked again when it's drawn
            raise RuntimeError("%s isn't ready" % self.name)
        return got

    def shape_ok(self, context):
        """False for the wrong shape, None when the fields say nothing (yet)."""
        ratio = _fill(self.spec.get("ratio"), context)
        if ratio:
            return image.croppable(float(ratio), 1)
        width, height = _fill(self.spec.get("width"), context), _fill(self.spec.get("height"), context)
        if width and height:
            return self.usable(int(float(width)), int(float(height)))
        return None

    def keys(self):
        spec = self.spec
        if not spec.get("url") or not spec.get("image"):
            log.warning("%s: a service needs url and image", self.name)
            return []
        if self.stasera and not (self.client and self.client.on):
            log.warning("%s: no stasera_url in the options", self.name)
            return []
        items, seen = {}, 0
        try:
            for q in self.queries or [""]:
                seen += self.search(q, items)
        except Unlinked:
            log.warning("%s: the add-on isn't linked to Stasera; link it on the add-on's page", self.name)
            return []
        if seen and not items:
            log.warning("%s: %d found, but none that can be used (id, image, width and height?)", self.name, seen)
        self.items = items
        return list(items)

    def search(self, query, items):
        """Adds what one query finds to items; the number found."""
        spec = self.spec
        start = _search(spec["url"].replace("{stasera}", self.client.base if self.stasera else ""), query)
        where = (spec.get("items") or "").replace("{query}", query)
        url, seen = start, 0
        for page in range(1, int(spec.get("pages") or self.PAGES) + 1):
            current = url.replace("{page}", str(page)).replace("{offset}", str(seen))
            try:
                got = self.answer(current)
            except urllib.error.HTTPError as e:
                if page == 1:
                    raise
                log.info("%s: page %d answered %s, that's the end", self.name, page, e.code)
                break
            found = _each(got, where)
            if not isinstance(found, list):
                if page == 1:
                    log.warning("%s: no list at %r in the answer", self.name, where)
                break
            for o in found:
                item = o if isinstance(o, dict) else {"id": o}
                if self.shape_ok(item) is False:
                    continue
                id_spec = spec.get("id") or ("id" if spec.get("steps") else None)
                key = _fill(id_spec, item) if id_spec else self.link(spec["image"], item)
                if key:
                    items.setdefault(key, item)
            seen += len(found)
            following = _fill(spec.get("next"), got)
            if not found or (not following and current == start):  # the end, or a url that doesn't page
                break
            if following:
                url = following
            time.sleep(float(spec.get("pause") or 0))
        return seen

    def context(self, key, steps=True):
        """All that's known about a key: the list's item, and the steps' answers."""
        spec = self.spec
        if key not in self.items and not spec.get("steps"):
            self.keys()  # after a restart
            if key not in self.items:
                raise RuntimeError("%s isn't in the answer now" % key)  # not Skip: it may come back
        context = dict(self.items.get(key) or {})
        if spec.get("id") or spec.get("steps"):
            context["id"] = key
        for n, step in enumerate((spec.get("steps") or []) if steps else [], 1):
            url = self.link(step, context)
            if not url:
                raise Skip("nothing for step %d" % n)
            try:
                context["step%d" % n] = self.ask(url)
            except urllib.error.HTTPError as e:
                if e.code in self.MISSING:
                    raise Skip("step %d answered %s" % (n, e.code))
                raise
        return context

    def allowed(self, context):
        """What the service has to say about each picture, like its license; unless is a field in the query that
        means the first isn't wanted ("medium", for a source that isn't paintings)."""
        unless = self.spec.get("unless")
        if unless and any(unless + "=" in q for q in self.queries):
            return
        for need in self.spec.get("require") or []:  # path=value, or path~text somewhere in it
            path, sign, wanted = re.split(r"([=~])", need, 1)
            found = _at(context, path)
            if (wanted not in json.dumps(found)) if sign == "~" else str(found).lower() != wanted.lower():
                raise Skip("%s isn't %s" % (path, wanted))

    def download(self, urls):
        """The first of the addresses that's there."""
        for url in urls:
            try:
                return net.get(url, timeout=180)
            except urllib.error.HTTPError as e:
                if e.code not in self.MISSING:
                    raise
        raise Skip("no picture at %s" % urls[0])

    def fetch(self, key):
        context = self.context(key)
        self.allowed(context)
        shape = self.shape_ok(context)
        if shape is False:
            raise Skip("not close to 16:9")
        small = self.link(self.spec.get("thumb"), context)
        if shape is None and small:  # the shape from the small copy; the original can be 50 MB
            if not image.croppable(*image.open_image(self.download([small])).size):
                raise Skip("not close to 16:9")
        urls = [u for u in (self.link(t, context) for t in re.split(r"\s+\|\s+", self.spec["image"])) if u]
        if not urls:
            raise Skip("no image")
        raw = self.download(urls)
        try:
            img = image.open_image(raw)
        except Exception as e:
            raise Skip("not a picture Pillow reads: %s" % e)
        self.check(*img.size)
        last = self.name
        for text in re.split(r"\s+\|\s+", self.spec.get("title") or ""):
            label = _fill(text, context)
            if label and _text(label):  # one too long or with a field missing gives way to the next
                return img, _text(label)
            last = _text(label, 1000) or last
        return img, last

    def thumb(self, key):
        spec = self.spec.get("thumb") or ""
        url = self.link(spec, self.context(key, "step" in spec))
        return url or Source.thumb(self, key)


def from_config(cfg, stasera=None):
    """The sources; a source's type is a service in the options, and what it sets itself goes before the service's."""
    entries = cfg["sources"] if "sources" in cfg else _old_options(cfg)
    services = {s["name"]: s for s in cfg.get("services") or []}
    out = []
    for e in entries:
        kind = e.get("type")
        if kind not in services and kind not in ("folder", "json"):
            log.warning("no service called %r (one of %s)", kind, ", ".join(services) or "none")
            continue
        name = re.sub(r"\s+", " ", (e.get("name") or kind).replace(":", " ")).strip()  # ": " ends the name
        if name in [s.name for s in out]:
            name += " %d" % (len(out) + 1)
        spec = dict(services.get(kind) or {}, **{k: v for k, v in e.items() if v not in (None, "")})
        src = (Folder if kind == "folder" else Web)(dict(spec, name=name), cfg)
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
