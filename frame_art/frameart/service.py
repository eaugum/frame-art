"""The rotation: every interval a random picture from a random source that's on, up to the TV, shown, and our older
uploads removed. It remembers in state.json what it uploaded (only those are ever deleted), what it showed lately
and when, so a restart of the Pi or the TV picks up where it was.

Two pictures we make have a time of their own (AUG-1447): Morgenbildet, with the date and the weather, at morning_time
(07:00), and tonight's show from Stasera as a poster at tonight_time (18:00). Each is shown once a day, as soon as its
time comes; the rotation goes on after it.

The rotation has a mode (AUG-1492): Shuffle draws from every category that's on, Kategori from one. A picture chosen
on the add-on's page (Fast bilde) stands until the next Morgenbildet, then the mode goes on. What wins is decided in
one place, wanted().

What the add-on's page changes (SETTINGS, and the fixed picture) is kept in settings.json, before the add-on's options.
"""
import asyncio
import datetime
import hashlib
import json
import logging
import os
import random
import time
from zoneinfo import ZoneInfo

from . import __version__, image, made, net, sources, weather
from .stasera import Stasera, Unlinked
from .tv import TV

log = logging.getLogger(__name__)

RECENT = 200  # not the same picture again within this many changes (or the whole pool, if it's smaller)
RETRY_MINUTES = 5  # TV off or away
MADE_RETRY_MINUTES = 15  # Open-Meteo, Stasera or TMDB didn't answer
MADE = ("morning", "tonight")
MODES = ("shuffle", "category")
HISTORY = 100  # pictures from the rotation remembered for «Nylig vist»
THUMBS = 600  # small copies kept for the add-on's page


def _bool(v):
    return v if isinstance(v, bool) else None


# What the add-on's page can change: name -> (default, check)
SETTINGS = {
    "interval_minutes": (60, lambda v: int(v) if 5 <= int(v) <= 1440 else None),
    "morning": (True, _bool),
    "morning_time": ("07:00", lambda v: datetime.time.fromisoformat(v).strftime("%H:%M")),
    "tonight": (True, _bool),
    "tonight_time": ("18:00", lambda v: datetime.time.fromisoformat(v).strftime("%H:%M")),
    "mode": ("shuffle", lambda v: v if v in MODES else None),
    "category": ("", lambda v: str(v).strip()),
    "categories_off": ([], lambda v: [str(c) for c in v] if isinstance(v, list) else None),
    # Kept for the screensaver (AUG-1494) and Følg musikken (AUG-1495); the page shows them already
    "screensaver_stasera": (True, _bool),
    "music": (False, _bool),
    "music_home_only": (True, _bool),
}
SCHEDULE = ("interval_minutes", "morning", "morning_time", "tonight", "tonight_time")


class State:
    def __init__(self, path):
        self.path = path
        try:
            with open(path) as f:
                self.d = json.load(f)
        except (OSError, ValueError):
            self.d = {}
        for k, v in (("uploaded", []), ("recent", []), ("bad", []), ("pools", {}), ("changed", 0), ("made", {}),
                     ("tried", {})):
            self.d.setdefault(k, v)

    def __getitem__(self, k):
        return self.d[k]

    def __setitem__(self, k, v):
        self.d[k] = v

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.d, f, indent=1)
        os.replace(tmp, self.path)


class Rotation:
    def __init__(self, cfg, data_dir):
        self.data = data_dir
        self.settings_path = os.path.join(data_dir, "settings.json")
        self.cfg = dict(cfg, **self._saved())
        self.state = State(os.path.join(data_dir, "state.json"))
        self.state.d.setdefault("history", [])
        self.sources = sources.from_config(cfg)
        self.by_name = {s.name: s for s in self.sources}
        self.categories = list(dict.fromkeys(s.category for s in self.sources))
        self.thumbs = os.path.join(data_dir, "thumbs")
        self.reading = set()  # categories whose sources are being listed for the page
        self.next_path = os.path.join(data_dir, "next.jpg")
        self.showing_path = os.path.join(data_dir, "showing.jpg")
        self.lock = asyncio.Lock()  # one conversation with the TV at a time: the timer, Home Assistant, Frame TV
        self.stasera = Stasera(cfg.get("stasera_url"), data_dir)
        self.zone = ZoneInfo(cfg.get("timezone") or os.environ.get("TZ") or "Europe/Oslo")

    # MARK: - Settings: the schedule, the mode and the fixed picture

    def _saved(self):
        try:
            with open(self.settings_path) as f:
                return {k: v for k, v in json.load(f).items() if k in SETTINGS or k == "fixed"}
        except (OSError, ValueError):
            return {}

    def _keep(self, changes):
        saved = dict(self._saved(), **changes)
        tmp = self.settings_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(saved, f, indent=1)
        os.replace(tmp, self.settings_path)
        self.cfg.update(changes)

    def settings(self):
        return {k: self.cfg.get(k, default) for k, (default, _) in SETTINGS.items()}

    def schedule(self):
        return {k: v for k, v in self.settings().items() if k in SCHEDULE}

    def set_settings(self, changes):
        """Checks and keeps what the add-on's page changed; raises ValueError on a bad value. A new mode or category
        ends a fixed picture: that's the newer choice."""
        clean = {}
        for k, v in changes.items():
            if k not in SETTINGS:
                raise ValueError("unknown setting %s" % k)
            try:
                clean[k] = SETTINGS[k][1](v)
            except (TypeError, ValueError):
                clean[k] = None
            if clean[k] is None:
                raise ValueError("bad value for %s: %r" % (k, v))
        if clean.get("category") and clean["category"] not in self.categories:
            raise ValueError("no category called %s" % clean["category"])
        after = dict(self.settings(), **clean)
        if after["mode"] == "category" and after["category"] not in self.categories:
            raise ValueError("choose a category")
        if ("mode" in clean or "category" in clean) and self.cfg.get("fixed"):
            clean["fixed"] = None
        self._keep(clean)
        log.info("settings: %s", ", ".join("%s=%s" % kv for kv in sorted(clean.items())))
        return self.settings()

    # Kept for the API's /schedule
    set_schedule = set_settings

    def fixed(self):
        """The picture you chose, while it stands: until the first morning_time after it was chosen."""
        f = self.cfg.get("fixed")
        if f and time.time() >= f.get("until", 0):
            log.info("the fixed picture has had its time; back to %s", self.cfg.get("mode", "shuffle"))
            self._keep({"fixed": None})
            return None
        return f

    def _next_morning(self):
        now = self.now()
        at = datetime.datetime.combine(now.date(), self._clock("morning_time"), tzinfo=self.zone)
        if at <= now:
            at = datetime.datetime.combine(now.date() + datetime.timedelta(days=1), self._clock("morning_time"),
                                           tzinfo=self.zone)
        return at.timestamp()

    def wanted(self):
        """What should be on the wall now: the first of these that has something to say (AUG-1490).

        1. Følg musikken, while music plays (AUG-1495)
        2. What you chose yourself: a fixed picture («neste» is a change right away)
        3. Morgenbildet and tonight's show; a fixed picture is ended by Morgenbildet, not by tonight's show
        4. The screensaver (AUG-1494)
        5. The rotation, in its mode
        """
        if self.fixed():
            return "fixed"
        return self.due() or "rotation"

    # MARK: - Picking

    def pool(self, src):
        p = self.state["pools"].get(src.name)
        if p and src.pool_hours and time.time() - p["at"] < src.pool_hours * 3600 and p["keys"]:
            return p["keys"]
        try:
            keys = src.keys()
            if not p or len(p["keys"]) != len(keys):
                log.info("%s: %d pictures", src.name, len(keys))
            self.state["pools"][src.name] = {"at": time.time(), "keys": keys}
            return keys
        except Exception as e:
            log.warning("%s: couldn't list pictures (%s)", src.name, e)
            return p["keys"] if p else []

    def in_play(self):
        """The sources the rotation draws from: in Kategori that category's, in Shuffle those of every category
        that's on."""
        if self.cfg.get("mode") == "category":
            return [s for s in self.sources if s.category == self.cfg.get("category")]
        off = set(self.cfg.get("categories_off") or [])
        return [s for s in self.sources if s.category not in off]

    def source_of(self, full):
        return self.by_name.get(full.split(":", 1)[0])

    def render(self, src, key):
        """(jpeg, label, full key) for one key; raises sources.Skip when it can't be used."""
        img, label = src.fetch(key)
        img = image.fill(img) if image.croppable(*img.size) else image.fit_on_blur(img)
        return image.to_jpeg(img), "%s: %s" % (src.name, label), src.name + ":" + key

    def pick(self):
        """(jpeg, label, key) for a new picture, or None."""
        bad, recent, empty = set(self.state["bad"]), self.state["recent"], set()
        for _ in range(12):
            # a source is listed only when it's drawn, so a big new one doesn't hold up the others
            choices = [s for s in self.in_play() if s.name not in empty]
            if not choices:
                return None
            src = random.choices(choices, [s.weight for s in choices])[0]
            keys = [k for k in self.pool(src) if src.name + ":" + k not in bad]
            if not keys:
                empty.add(src.name)
                continue
            fresh = [k for k in keys if src.name + ":" + k not in recent[-min(RECENT, len(keys) - 1):]] or keys
            key = random.choice(fresh)
            full = src.name + ":" + key
            try:
                return self.render(src, key)
            except sources.Skip as e:
                log.info("skipping %s: %s", full, e)
                self.state["bad"].append(full)
                bad.add(full)
            except Exception as e:
                log.warning("couldn't fetch %s: %s", full, e)
        return None

    # MARK: - The pictures we make

    def now(self):
        return datetime.datetime.now(self.zone)

    def _clock(self, name):
        try:
            return datetime.time.fromisoformat(self.cfg.get(name) or SCHEDULE[name][0])
        except ValueError:
            return datetime.time.fromisoformat(SCHEDULE[name][0])

    def due(self):
        """'tonight' or 'morning' when its time has come and it hasn't been shown today, else None."""
        now = self.now()
        today, clock = now.date().isoformat(), now.time()
        evening = self._clock("tonight_time")
        for kind, on, start, end in (
                ("tonight", self.cfg.get("tonight", True) and self.stasera.state() == "linked", evening,
                 datetime.time.max),
                ("morning", self.cfg.get("morning", True), self._clock("morning_time"), evening)):
            if not on or not start <= clock < end or self.state["made"].get(kind) == today:
                continue
            if time.time() - self.state["tried"].get(kind, 0) < MADE_RETRY_MINUTES * 60:
                continue
            return kind
        return None

    def make(self, kind):
        """(jpeg, label, key) for Morgenbildet or tonight's poster, or None (and it's tried again later)."""
        now = self.now()
        today = now.date().isoformat()
        try:
            if kind == "morning":
                try:
                    w = weather.today(self.cfg.get("latitude", 59.9139), self.cfg.get("longitude", 10.7522))
                except Exception as e:
                    log.warning("no weather for Morgenbildet (%s)", e)
                    w = None
                img, label = made.morning_picture(now, w), "Morgenbildet"
            else:
                items = [i for i in self.stasera.tonight() if i.get("textlessBackdropPath") or i.get("backdropPath")]
                if not items:
                    log.info("nothing in Stasera tonight")
                    self.state["made"][kind] = today  # not again today
                    self.state.save()
                    return None
                img, label = made.poster(items[0]), "I kveld: %s" % (items[0].get("title") or "?")
        except Unlinked:
            log.info("Stasera isn't linked: link it on the add-on's page")
            return None
        except Exception as e:
            log.warning("couldn't make %s (%s: %s)", kind, type(e).__name__, e)
            self.state["tried"][kind] = time.time()
            self.state.save()
            return None
        return image.to_jpeg(img), label, "%s:%s" % (kind, today)

    def prepared(self, what=None):
        """The picture for the next change, made once and kept until it's on the TV (the TV may be off for hours).
        what ('morning' or 'tonight') makes that one now; otherwise one that's due comes before the rotation."""
        meta = self.state.d.get("next")
        kind = what or self.due()
        if meta and meta.get("made") and meta["key"] != "%s:%s" % (kind, self.now().date().isoformat()):
            meta = None  # yesterday's, or Morgenbildet still waiting when it's time for the poster
        if meta and kind and not meta.get("made"):
            meta = None  # a picture from the rotation gives way
        if meta and not meta.get("made") and self.source_of(meta["key"]) not in self.in_play():
            meta = None  # from a category that's no longer in play
        if meta and os.path.exists(self.next_path):
            with open(self.next_path, "rb") as f:
                return f.read(), meta["label"], meta["key"]
        got = self.make(kind) if kind else None
        if not got and what:
            return None
        if not got:
            got = self.pick()
        if got:
            with open(self.next_path, "wb") as f:
                f.write(got[0])
            self.state["next"] = {"label": got[1], "key": got[2], "made": got[2].split(":")[0] in MADE}
            self.state.save()
        return got

    # MARK: - The TV

    async def change(self, art_mode=False, what=None):
        """A new picture. With art_mode, the TV goes to Art Mode too (Home Assistant, Frame TV); the timer never does.
        what: 'morning' or 'tonight' for that one now. It ends a fixed picture (the timer doesn't change one)."""
        async with self.lock:
            ok = await self._change(art_mode, what)
            if ok and self.cfg.get("fixed"):
                self._keep({"fixed": None})
            return ok

    async def choose(self, full):
        """A picture you chose on the add-on's page: shown now, in Art Mode, standing until the next Morgenbildet."""
        src = self.source_of(full)
        if not src:
            raise ValueError("no source called %s" % full.split(":", 1)[0])
        async with self.lock:
            try:
                got = await asyncio.to_thread(self.render, src, full.split(":", 1)[1])
            except sources.Skip as e:
                self.state["bad"].append(full)
                self.state.save()
                raise ValueError("that picture can't be used (%s)" % e)
            await self._put(*got, force=True)
            self._keep({"fixed": {"key": full, "label": got[1], "until": self._next_morning()}})
            log.info("fixed until %s", datetime.datetime.fromtimestamp(self.cfg["fixed"]["until"], self.zone))
        return True

    async def _change(self, force, what=None):
        got = await asyncio.to_thread(self.prepared, what)
        if not got:
            log.warning("nothing to show: %s", "couldn't make %s" % what if what else
                        "no source is on, or none has pictures")
            return False
        await self._put(*got, force=force, prepared=True)
        return True

    async def _put(self, jpeg, label, key, force, prepared=False):
        """Up to the TV and shown (or ready for Art Mode); raises when the TV doesn't answer."""
        log.info("connecting to the TV for %s", label)
        async with TV(self.cfg["tv_host"], os.path.join(self.data, "token.txt")) as tv:
            art_mode = await tv.in_art_mode()
            content_id = await tv.upload(jpeg)
            if not content_id:
                raise RuntimeError("the TV didn't say it got the picture")
            if force and not art_mode:
                await tv.art_mode_on()
                art_mode = True
            await tv.show(content_id, now=art_mode)
            log.info("%s %s (%s)", "showing" if art_mode else "ready for Art Mode:", label, content_id)
            if await tv.slideshow_on():
                log.warning("the TV's own slideshow is on and will change the picture too")

            self.state["uploaded"].append({"content_id": content_id, "key": key, "at": int(time.time())})
            self.state["recent"] = (self.state["recent"] + [key])[-RECENT:]
            self.state["changed"] = time.time()
            self.state["showing"] = label
            kind, _, day = key.partition(":")
            if kind in MADE:
                self.state["made"][kind] = day
            else:
                self.state["history"] = (self.state["history"] + [{"key": key, "label": label,
                                                                    "at": int(time.time())}])[-HISTORY:]
            if prepared:
                self.state.d.pop("next", None)
            self.state.save()
            with open(self.showing_path + ".tmp", "wb") as f:  # for the add-on's page
                f.write(jpeg)
            os.replace(self.showing_path + ".tmp", self.showing_path)
            if prepared and os.path.exists(self.next_path):
                os.remove(self.next_path)
            if kind not in MADE:
                try:
                    self._keep_thumb(key, image.thumbnail(image.open_image(jpeg, draft=image.THUMB)))
                except Exception as e:
                    log.debug("no thumbnail for %s (%s)", key, e)
            try:
                await self.clean(tv)
            except Exception as e:  # the picture is up; what's left is cleaned next time
                log.warning("couldn't clean up (%s: %s)", type(e).__name__, e)

    async def art_mode(self):
        """Art Mode on, with the picture it has."""
        async with self.lock:
            async with TV(self.cfg["tv_host"], os.path.join(self.data, "token.txt")) as tv:
                if not await tv.in_art_mode():
                    await tv.art_mode_on()
                    log.info("Art Mode on")
        return True

    def status(self):
        interval = self.interval()
        # None: not listed yet (a source is listed the first time it's drawn); 0: listed, and nothing found
        pools = {s.name: len(self.state["pools"][s.name].get("keys") or []) if s.name in self.state["pools"] else None
                 for s in self.sources}
        off = set(self.cfg.get("categories_off") or [])
        categories = []
        for c in self.categories:
            names = [s.name for s in self.sources if s.category == c]
            counts = [pools[n] for n in names if pools[n] is not None]
            categories.append({"name": c, "on": c not in off, "sources": names,
                               "pictures": sum(counts) if counts else None, "unread": len(names) - len(counts)})
        fixed = self.fixed()
        rotating = not fixed
        return {"version": __version__, "showing": self.state.d.get("showing"), "changed": int(self.state["changed"]),
                "next": int(self.state["changed"] + interval) if self.state["changed"] and rotating else None,
                "interval_minutes": interval / 60, "sources": [s.name for s in self.sources],
                "source_categories": {s.name: s.category for s in self.sources},
                "pools": pools, "schedule": self.schedule(), "settings": self.settings(),
                "mode": "fixed" if fixed else self.cfg.get("mode", "shuffle"), "category": self.cfg.get("category"),
                "categories": categories, "fixed": fixed, "wanted": self.wanted(),
                "stasera": self.stasera.state(), "pairing": self.stasera.pairing, "busy": self.lock.locked()}

    # MARK: - The add-on's page: choosing a picture

    def _thumb_path(self, full):
        return os.path.join(self.thumbs, hashlib.sha1(full.encode()).hexdigest() + ".jpg")

    def _keep_thumb(self, full, jpeg):
        os.makedirs(self.thumbs, exist_ok=True)
        with open(self._thumb_path(full), "wb") as f:
            f.write(jpeg)
        files = sorted(os.scandir(self.thumbs), key=lambda e: e.stat().st_mtime)
        for e in files[:max(0, len(files) - THUMBS)]:
            os.remove(e.path)

    def thumb(self, full):
        """A small JPEG of a picture, kept; raises sources.Skip or a network error."""
        path = self._thumb_path(full)
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read()
        src = self.source_of(full)
        if not src:
            raise sources.Skip("no such source")
        got = src.thumb(full.split(":", 1)[1])
        img = image.open_image(net.get(got), draft=image.THUMB) if isinstance(got, str) else got
        jpeg = image.thumbnail(img)
        self._keep_thumb(full, jpeg)
        return jpeg

    def _read(self, category):
        try:
            for s in self.sources:
                if s.category == category and s.name not in self.state["pools"]:
                    self.pool(s)
            self.state.save()
        finally:
            self.reading.discard(category)

    async def gallery(self, category, n=24):
        """For a category: what's been on the wall lately (newest first), and n at random from what it has. Sources
        not listed yet are listed in the background; «reading» says which."""
        if category not in self.categories:
            raise ValueError("no category called %s" % category)
        names = {s.name for s in self.sources if s.category == category}
        recent, seen = [], set()
        for h in reversed(self.state["history"]):
            if h["key"] not in seen and h["key"].split(":", 1)[0] in names:
                seen.add(h["key"])
                recent.append({"key": h["key"], "label": h["label"].split(": ", 1)[-1]})
        bad = set(self.state["bad"])
        keys = [name + ":" + k for name in names for k in (self.state["pools"].get(name) or {}).get("keys") or []]
        keys = [k for k in keys if k not in bad]
        unlisted = sorted(name for name in names if name not in self.state["pools"])
        if unlisted and category not in self.reading:
            self.reading.add(category)
            asyncio.get_running_loop().run_in_executor(None, self._read, category)
        return {"category": category, "recent": recent[:n],
                "random": [{"key": k} for k in random.sample(keys, min(n, len(keys)))], "reading": unlisted}

    async def clean(self, tv):
        """Deletes our own older uploads, keeping the newest few; never anything else in «Mine bilder»."""
        keep = max(1, int(self.cfg.get("keep", 3)))
        on_tv = await tv.my_photos()  # raises rather than giving an empty list, so nothing is forgotten by mistake
        ours = [u for u in self.state["uploaded"] if u["content_id"] in on_tv]  # forget what someone deleted
        old = ours[:-keep]
        if old:
            await tv.delete(u["content_id"] for u in old)
            log.info("deleted %d older pictures", len(old))
        self.state["uploaded"] = ours[-keep:]
        self.state.save()

    # MARK: - Running

    def interval(self):
        return max(1, float(self.cfg.get("interval_minutes", 60))) * 60

    async def run(self):
        log.info("Frame Art %s for %s, every %g min, sources: %s", __version__, self.cfg["tv_host"],
                 self.interval() / 60, ", ".join(s.name for s in self.sources) or "none")
        while True:
            wait = self.state["changed"] + self.interval() - time.time()  # the interval can change on the page
            want = self.wanted()
            if want == "fixed" or (want == "rotation" and wait > 0):
                await asyncio.sleep(min(wait, 60) if wait > 0 else 60)  # the API moves the time; look each minute
                continue
            try:
                ok = await self.change()
            except Exception as e:
                # off, away, or busy with something that stops the art app (AirPlay, some apps): never interrupted
                log.info("Art Mode not answering (%s: %s); trying again in %d min", type(e).__name__, e, RETRY_MINUTES)
                ok = False
            if not ok:
                await asyncio.sleep(RETRY_MINUTES * 60)
