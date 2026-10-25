"""The rotation: every interval a random picture from a random source that's on, up to the TV, shown, and our older
uploads removed. It remembers in state.json what it uploaded (only those are ever deleted), what it showed lately
and when, so a restart of the Pi or the TV picks up where it was.

Two pictures we make have a time of their own (AUG-1447): Morgenbildet, with the date and the weather, at morning_time
(07:00), and tonight's show from Stasera as a poster at tonight_time (18:00). Each is shown once a day, as soon as its
time comes; the rotation goes on after it. The schedule can be changed on the add-on's page (SCHEDULE), and that is
kept in settings.json, before the add-on's options.
"""
import asyncio
import datetime
import json
import logging
import os
import random
import time
from zoneinfo import ZoneInfo

from . import __version__, image, made, sources, weather
from .stasera import Stasera, Unlinked
from .tv import TV

log = logging.getLogger(__name__)

RECENT = 200  # not the same picture again within this many changes (or the whole pool, if it's smaller)
RETRY_MINUTES = 5  # TV off or away
MADE_RETRY_MINUTES = 15  # Open-Meteo, Stasera or TMDB didn't answer
MADE = ("morning", "tonight")

# What the add-on's page can change: name -> (default, check)
SCHEDULE = {
    "interval_minutes": (60, lambda v: int(v) if 5 <= int(v) <= 1440 else None),
    "morning": (True, lambda v: v if isinstance(v, bool) else None),
    "morning_time": ("07:00", lambda v: datetime.time.fromisoformat(v).strftime("%H:%M")),
    "tonight": (True, lambda v: v if isinstance(v, bool) else None),
    "tonight_time": ("18:00", lambda v: datetime.time.fromisoformat(v).strftime("%H:%M")),
}


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
        self.cfg = dict(cfg, **self._saved_schedule())
        self.state = State(os.path.join(data_dir, "state.json"))
        self.sources = sources.from_config(cfg)
        self.next_path = os.path.join(data_dir, "next.jpg")
        self.showing_path = os.path.join(data_dir, "showing.jpg")
        self.lock = asyncio.Lock()  # one conversation with the TV at a time: the timer, Home Assistant, Frame TV
        self.stasera = Stasera(cfg.get("stasera_url"), data_dir)
        self.zone = ZoneInfo(cfg.get("timezone") or os.environ.get("TZ") or "Europe/Oslo")

    # MARK: - The schedule

    def _saved_schedule(self):
        try:
            with open(self.settings_path) as f:
                return {k: v for k, v in json.load(f).items() if k in SCHEDULE}
        except (OSError, ValueError):
            return {}

    def schedule(self):
        return {k: self.cfg.get(k, default) for k, (default, _) in SCHEDULE.items()}

    def set_schedule(self, changes):
        """Checks and keeps what the add-on's page changed; raises ValueError on a bad value."""
        clean = {}
        for k, v in changes.items():
            if k not in SCHEDULE:
                raise ValueError("unknown setting %s" % k)
            try:
                clean[k] = SCHEDULE[k][1](v)
            except (TypeError, ValueError):
                clean[k] = None
            if clean[k] is None:
                raise ValueError("bad value for %s: %r" % (k, v))
        saved = dict(self._saved_schedule(), **clean)
        tmp = self.settings_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(saved, f, indent=1)
        os.replace(tmp, self.settings_path)
        self.cfg.update(clean)
        log.info("schedule: %s", ", ".join("%s=%s" % kv for kv in sorted(clean.items())))
        return self.schedule()

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

    def pick(self):
        """(jpeg, label, key) for a new picture, or None."""
        bad, recent, empty = set(self.state["bad"]), self.state["recent"], set()
        for _ in range(12):
            # a source is listed only when it's drawn, so a big new one doesn't hold up the others
            choices = [s for s in self.sources if s.name not in empty]
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
                img, label = src.fetch(key)
            except sources.Skip as e:
                log.info("skipping %s: %s", full, e)
                self.state["bad"].append(full)
                bad.add(full)
                continue
            except Exception as e:
                log.warning("couldn't fetch %s: %s", full, e)
                continue
            img = image.fill(img) if image.croppable(*img.size) else image.fit_on_blur(img)
            return image.to_jpeg(img), "%s: %s" % (src.name, label), full
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
        what: 'morning' or 'tonight' for that one now."""
        async with self.lock:
            return await self._change(art_mode, what)

    async def _change(self, force, what=None):
        got = await asyncio.to_thread(self.prepared, what)
        if not got:
            log.warning("nothing to show: %s", "couldn't make %s" % what if what else
                        "no source is on, or none has pictures")
            return False
        jpeg, label, key = got
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
            self.state.d.pop("next", None)
            self.state.save()
            os.replace(self.next_path, self.showing_path)  # for the add-on's page
            try:
                await self.clean(tv)
            except Exception as e:  # the picture is up; what's left is cleaned next time
                log.warning("couldn't clean up (%s: %s)", type(e).__name__, e)
        return True

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
        pools = {s.name: len((self.state["pools"].get(s.name) or {}).get("keys") or []) for s in self.sources}
        return {"version": __version__, "showing": self.state.d.get("showing"), "changed": int(self.state["changed"]),
                "next": int(self.state["changed"] + interval) if self.state["changed"] else None,
                "interval_minutes": interval / 60, "sources": [s.name for s in self.sources],
                "pools": pools, "schedule": self.schedule(), "stasera": self.stasera.state(),
                "pairing": self.stasera.pairing, "busy": self.lock.locked()}

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
            if wait > 0 and not self.due():
                await asyncio.sleep(min(wait, 60))  # a change from the API moves the time; look again each minute
                continue
            try:
                ok = await self.change()
            except Exception as e:
                # off, away, or busy with something that stops the art app (AirPlay, some apps): never interrupted
                log.info("Art Mode not answering (%s: %s); trying again in %d min", type(e).__name__, e, RETRY_MINUTES)
                ok = False
            if not ok:
                await asyncio.sleep(RETRY_MINUTES * 60)
