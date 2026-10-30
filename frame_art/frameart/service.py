"""The rotation: every interval a random picture from a random source that's on, up to the TV, shown, and our older
uploads removed. It remembers in state.json what it uploaded (only those are ever deleted), what it showed lately
and when, so a restart of the Pi or the TV picks up where it was.

Two pictures we make have a time of their own (AUG-1447): Morgenbildet, with the date and the weather, at morning_time
(07:00), and tonight's show from Stasera as a poster at tonight_time (18:00). Each is shown once a day, as soon as its
time comes; the rotation goes on after it.

The rotation draws from the sources that are ticked on the add-on's page (sources_off are the others); they're grouped
in categories only to be found. A picture chosen on the add-on's page (a fixed picture) stands until the next Morgenbildet,
then the rotation goes on. What wins is decided in one place, wanted().

Frame TV's screensaver (AUG-1494) says so with POST /saver: Art Mode on, and with screensaver_stasera what we watch and
want to start in Stasera, with the title, in turn with the interval, until Art Mode goes off. Art Mode going off while
the TV is on opens Frame TV, since the remote's keys only give the TV's own Art Mode menu.

Follow the music (AUG-1495): while Spotify plays (read from Home Assistant), the album's cover with the song, a picture
per song, in front of everything else. A few minutes after it stops, what was on the wall before comes back.

What the add-on's page changes (SETTINGS, and the fixed picture) is kept in settings.json, before the add-on's options.
"""
import asyncio
import datetime
import hashlib
import json
import logging
import os
import random
import shutil
import time
from zoneinfo import ZoneInfo

from . import __version__, events, i18n, image, made, music, net, sources, today as todaymod, weather
from .i18n import t
from .stasera import Stasera, Unlinked
from . import tv as tvmod
from .tv import TV

log = logging.getLogger(__name__)

RECENT = 200  # not the same picture again within this many changes (or the whole pool, if it's smaller)
RETRY_MINUTES = 5  # TV off or away
MADE_RETRY_MINUTES = 15  # Stasera didn't answer
MADE_UNSEEN_MINUTES = 10  # the TV off this soon after Morgenbildet or tonight's show: it stays until it's seen
MADE = ("morning", "tonight")
EVENT_SOURCES = ("morning", "tonight", "music", "saver")  # a picture's kind -> the event log's source; else rotation
MODES = ("shuffle", "category")  # "category" only from older callers: it becomes that category's sources
SAVER = {"watching": "watching", "wantToStart": "want_to_start"}  # Stasera's lists for the screensaver -> the heading
HISTORY = 100  # pictures from the rotation remembered for "Recently shown"
THUMBS = 600  # small copies kept for the add-on's page
OWN = ("saver", "music")  # pictures of the moment: not in "Recently shown", and not prepared ahead
MUSIC_LOOK = 4  # seconds between looks at Home Assistant's player
MUSIC_GRACE = 3 * 60  # paused or stopped this long, and the music has stopped
TV_ON_WAIT = 30  # seconds from Home Assistant turning the TV on until Art Mode answers
WAKE_WAIT = 90  # seconds the page's "Turn the TV on" waits for the TV to say it's on
POWER_LOOK = 20  # seconds between asking the TV whether it's on, for the event log (AUG-1523)
SEEN = {"power_on": "the TV came on", "power_off": "the TV went off", "art_mode_on": "Art Mode on",
        "art_mode_off": "Art Mode off"}


def _bool(v):
    return v if isinstance(v, bool) else None


# What the add-on's page can change: name -> (default, check)
SETTINGS = {
    "interval_minutes": (60, lambda v: int(v) if 5 <= int(v) <= 1440 else None),
    "keep": (3, lambda v: int(v) if 1 <= int(v) <= 20 else None),  # our own pictures left on the TV
    "morning": (True, _bool),
    "morning_time": ("07:00", lambda v: datetime.time.fromisoformat(v).strftime("%H:%M")),
    "tonight": (True, _bool),
    "tonight_time": ("18:00", lambda v: datetime.time.fromisoformat(v).strftime("%H:%M")),
    "mode": ("shuffle", lambda v: v if v in MODES else None),
    "category": ("", lambda v: str(v).strip()),
    "categories_off": ([], lambda v: [str(c) for c in v] if isinstance(v, list) else None),  # before sources_off
    "sources_off": ([], lambda v: [str(c) for c in v] if isinstance(v, list) else None),
    # Kept for the screensaver (AUG-1494) and Follow the music (AUG-1495); the page shows them already
    # The TV (tv_entity in the options) turned on through Home Assistant before Morgenbildet and tonight's show,
    # when it's off
    "morning_tv_on": (True, _bool),
    "tonight_tv_on": (True, _bool),
    "screensaver": (True, _bool),  # off: Frame TV doesn't start its screensaver (it reads this from /status)
    "screensaver_stasera": (True, _bool),
    "music": (False, _bool),
    # Only when someone is home (home_entity in the options): Follow the music and turning the TV on. The name is
    # from when it was only the music; it's kept for switch.frame_art_music_home_only
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
        self.stasera = Stasera(cfg.get("stasera_url"), data_dir)
        self.sources = sources.from_config(cfg, self.stasera)
        self.by_name = {s.name: s for s in self.sources}
        self.categories = list(dict.fromkeys(s.category for s in self.sources))
        self.thumbs = os.path.join(data_dir, "thumbs")
        self.reading = set()  # categories whose sources are being listed for the page; "*" all of them
        self.next_path = os.path.join(data_dir, "next.jpg")
        self.showing_path = os.path.join(data_dir, "showing.jpg")
        self.lock = asyncio.Lock()  # one conversation with the TV at a time: the timer, Home Assistant, Frame TV
        self.zone = ZoneInfo(cfg.get("timezone") or os.environ.get("TZ") or "Europe/Oslo")
        self.saver = False  # Frame TV's screensaver is on, until Art Mode goes off
        self.saver_minutes = None  # how often the picture changes meanwhile, from Frame TV
        self.back_at = 0  # when Frame TV was last opened; the TV says "off" twice
        self.away_logged = None  # the day "nobody home" was last in the log
        self.before_path = os.path.join(data_dir, "before.jpg")  # what was on the wall when the music started
        self.ha = music.HomeAssistant(cfg)
        i18n.setup(cfg)
        self.music, self.music_at = None, 0  # what played last, and when it was last seen playing
        self.wake = asyncio.Event()  # the music changed: the timer looks at once
        self.retry_at = 0  # the TV didn't answer: a new song doesn't try again before this
        self.listened = asyncio.Event()  # the player has been looked at once since the start
        self.seen = {"power": None, "art_mode": None}  # what the TV was last seen doing; None: not known
        self.waiting = False  # the rotation waits for Art Mode (AUG-1526)
        self._from_categories()

    def _from_categories(self):
        """Settings from before sources_off: Kategori or the categories that were off become the sources that are."""
        if "sources_off" in self._saved():
            return
        if self.cfg.get("mode") == "category" and self.cfg.get("category") in self.categories:
            off = [s.name for s in self.sources if s.category != self.cfg["category"]]
        else:
            cats = set(self.cfg.get("categories_off") or [])
            off = [s.name for s in self.sources if s.category in cats]
        self._keep({"sources_off": off, "mode": "shuffle"})

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
        if clean.get("mode") == "category":  # only that category's sources, from Home Assistant or an older caller
            c = clean.get("category") or self.cfg.get("category")
            if c not in self.categories:
                raise ValueError("choose a category")
            clean.update(mode="shuffle", category=c, sources_off=[s.name for s in self.sources if s.category != c])
        if "sources_off" in clean:  # a source renamed or gone in the options is forgotten
            clean["sources_off"] = [n for n in dict.fromkeys(clean["sources_off"]) if n in self.by_name]
        if ("mode" in clean or "sources_off" in clean) and self.cfg.get("fixed"):
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
            log.info("the fixed picture has had its time; back to the rotation")
            events.add("rotation", "fixed_over", "the fixed picture has had its time; back to the rotation",
                       why="the next morning picture")
            self._keep({"fixed": None})
            return None
        return f

    def fix_showing(self):
        """What's on the wall now becomes the fixed picture (from Home Assistant's mode select)."""
        if not self.state["recent"]:
            raise ValueError("nothing shown yet")
        self._keep({"fixed": {"key": self.state["recent"][-1], "label": self.state.d.get("showing"),
                              "until": self._next_morning()}})
        log.info("fixed what's showing until the next Morgenbildet")
        events.add("rotation", "fixed", "%s, until the next morning picture" % self.state.d.get("showing"))

    def _next_morning(self):
        now = self.now()
        at = datetime.datetime.combine(now.date(), self._clock("morning_time"), tzinfo=self.zone)
        if at <= now:
            at = datetime.datetime.combine(now.date() + datetime.timedelta(days=1), self._clock("morning_time"),
                                           tzinfo=self.zone)
        return at.timestamp()

    def wanted(self):
        """What should be on the wall now: the first of these that has something to say (AUG-1490).

        1. Follow the music, while music plays (AUG-1495)
        2. What you chose yourself: a fixed picture ("next" is a change right away)
        3. Morgenbildet and tonight's show; a fixed picture is ended by Morgenbildet, not by tonight's show
        4. The screensaver, with Stasera's pictures (AUG-1494)
        5. The rotation, in its mode
        """
        if self.playing():
            return "music"
        if self.fixed():
            return "fixed"
        due = self.due()
        if due:
            return due
        if self.saver and self.cfg.get("screensaver_stasera", True) and self.stasera.state() == "linked":
            return "saver"
        return "rotation"

    # MARK: - Picking

    def pool(self, src):
        p = self.state["pools"].get(src.name)
        if p and p.get("wide") and src.pool_hours and time.time() - p["at"] < src.pool_hours * 3600 and p["keys"]:
            return p["keys"]  # wide: listed since only 16:9 is used (0.14.0)
        try:
            keys = src.keys()
            if not p or len(p["keys"]) != len(keys):
                log.info("%s: %d pictures", src.name, len(keys))
            self.state["pools"][src.name] = {"at": time.time(), "keys": keys, "wide": True}
            return keys
        except Exception as e:
            log.warning("%s: couldn't list pictures (%s)", src.name, e)
            return p["keys"] if p else []

    def in_play(self):
        """The sources the rotation draws from: those that are ticked."""
        off = set(self.cfg.get("sources_off") or [])
        return [s for s in self.sources if s.name not in off]

    def source_of(self, full):
        return self.by_name.get(full.split(":", 1)[0])

    def render(self, src, key):
        """(jpeg, label, full key) for one key; raises sources.Skip when it can't be used."""
        img, label = src.fetch(key)
        if not image.croppable(*img.size):
            raise sources.Skip("%dx%d isn't close to 16:9" % img.size)
        img = image.fill(img)
        return image.to_jpeg(img), "%s: %s" % (src.name, label), src.name + ":" + key

    def pick(self):
        """(jpeg, label, key) for a new picture, or None."""
        bad, recent, empty = set(self.state["bad"]), self.state["recent"], set()
        for _ in range(12):
            # a source is listed only when it's drawn, so a big new one doesn't hold up the others
            choices = [s for s in self.in_play() if s.name not in empty]
            if not choices:
                return None
            src = random.choice(choices)
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
                events.add("rotation", "fetch_failed", "couldn't fetch %s: %s" % (full, e))
        return None

    # MARK: - The pictures we make

    def now(self):
        return datetime.datetime.now(self.zone)

    def _clock(self, name):
        try:
            return datetime.time.fromisoformat(self.cfg.get(name) or SETTINGS[name][0])
        except ValueError:
            return datetime.time.fromisoformat(SETTINGS[name][0])

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
                w = self.weather(now)
                img, label = made.morning_picture(now, w, self._day(now)), "Morning picture"
            else:
                items = [i for i in self.stasera.tonight() if i.get("textlessBackdropPath") or i.get("backdropPath")]
                if not items:
                    log.info("nothing in Stasera tonight")
                    events.add(kind, "nothing", "nothing in Stasera tonight")
                    self.state["made"][kind] = today  # not again today
                    self.state.save()
                    return None
                img, label = made.poster(items[0]), "Tonight: %s" % (items[0].get("title") or "?")
        except Unlinked:
            log.info("Stasera isn't linked: link it on the add-on's page")
            events.add(kind, "unlinked", "Stasera isn't linked")
            return None
        except Exception as e:
            log.warning("couldn't make %s (%s: %s)", kind, type(e).__name__, e)
            events.add(kind, "failed", "couldn't make it (%s: %s); trying again in %d min" % (
                type(e).__name__, e, MADE_RETRY_MINUTES))
            self.state["tried"][kind] = time.time()
            self.state.save()
            return None
        return image.to_jpeg(img), label, "%s:%s" % (kind, today)

    def weather(self, now):
        """Today's weather for Morgenbildet, from weather_entity in Home Assistant; None without one, or when it
        doesn't answer (the picture comes without the weather)."""
        entity = self.cfg.get("weather_entity")
        if not entity or not self.ha.ready():
            return None
        try:
            return weather.from_ha(self.ha, entity, now)
        except Exception as e:
            log.warning("no weather from %s (%s: %s)", entity, type(e).__name__, e)
            return None

    def _day(self, now):
        """What else Morgenbildet says (today.py); what doesn't answer is left out."""
        ha = self.ha.ready()
        return {"names": todaymod.names(now),
                "events": todaymod.events(self.ha, self.cfg.get("calendars") or [], now) if ha else [],
                "shows": todaymod.shows(self.stasera, now.date()) if self.stasera.state() == "linked" else [],
                "power": todaymod.power(self.ha, self.cfg["price_entity"], now)
                if ha and self.cfg.get("price_entity") else None}

    def make_saver(self):
        """(jpeg, label, key) for the screensaver: the next of what we watch and want to start, in turn, or None."""
        try:
            items = [i for i in self.stasera.titles(list(SAVER)) if i.get("textlessBackdropPath") or
                     i.get("backdropPath")]
        except Unlinked:
            return None
        except Exception as e:
            log.warning("nothing from Stasera for the screensaver (%s: %s)", type(e).__name__, e)
            events.add("saver", "failed", "nothing from Stasera (%s: %s)" % (type(e).__name__, e))
            return None
        if not items:
            log.info("nothing in Stasera for the screensaver")
            events.add("saver", "nothing", "nothing in Stasera for the screensaver")
            return None
        # the next episode is in the key, so a new one makes a new picture
        keys = ["saver:%s:%s%s" % (i.get("kind"), i.get("tmdbId"), ":%sx%s" % (i["seasonNumber"], i.get(
            "episodeNumber")) if i.get("kind") == "show" and i.get("seasonNumber") is not None else "") for i in items]
        recent = self.state["recent"][-(len(keys) - 1):] if len(keys) > 1 else []
        n = next((n for n, k in enumerate(keys) if k not in recent), 0)
        try:
            img = made.poster(items[n], t(SAVER[items[n]["list"]]))
        except Exception as e:
            log.warning("couldn't make the screensaver's picture (%s: %s)", type(e).__name__, e)
            events.add("saver", "failed", "couldn't make the picture (%s: %s)" % (type(e).__name__, e))
            return None
        return image.to_jpeg(img), "Stasera: %s" % (items[n].get("title") or "?"), keys[n]

    def make_music(self):
        """(jpeg, label, key) for the album that plays, or None."""
        m = self.music
        try:
            cover = image.open_image(self.ha.cover(m["cover"]))
            img = made.music_picture(cover, m["title"], m["artist"], m["album"])
        except Exception as e:
            log.warning("couldn't make the cover's picture (%s: %s)", type(e).__name__, e)
            events.add("music", "failed", "couldn't make the cover's picture (%s: %s)" % (type(e).__name__, e))
            return None
        return image.to_jpeg(img), "Music: %s – %s" % (m["title"], m["artist"]), m["key"]

    def prepared(self, what=None):
        """The picture for the next change, made once and kept until it's on the TV (the TV may be off for hours).
        what ('morning' or 'tonight') makes that one now; otherwise one that's due comes before the rotation."""
        if what == "music":
            return self.make_music()
        if what == "saver":
            got = self.make_saver()
            if got:
                return got
            what = None  # the rotation, rather than nothing
        meta = self.state.d.get("next")
        kind = what or self.due()
        if meta and meta.get("made") and meta["key"] != "%s:%s" % (kind, self.now().date().isoformat()):
            meta = None  # yesterday's, or Morgenbildet still waiting when it's time for the poster
        if meta and kind and not meta.get("made"):
            meta = None  # a picture from the rotation gives way
        if meta and not meta.get("made") and self.source_of(meta["key"]) not in self.in_play():
            meta = None  # from a source that's no longer ticked
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
            if ok and self.cfg.get("fixed") and what != "music":
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
            events.add("rotation", "fixed", "%s, until the next morning picture" % got[1])
        return True

    def showing_key(self):
        """The key of what's on the wall, when it's from a source (not one of the pictures we make), else None."""
        last = self.state["recent"][-1] if self.state["recent"] else ""
        kind = last.split(":", 1)[0]
        return last if kind not in MADE + OWN and self.source_of(last) else None

    async def never(self):
        """What's on the wall is never drawn again (a backdrop with a logo TMDB didn't mark, a picture you don't
        like), and another one comes."""
        key = self.showing_key()
        if not key:
            raise ValueError("only a picture from the sources can be left out")
        if key not in self.state["bad"]:
            self.state["bad"].append(key)
        self.state["history"] = [h for h in self.state["history"] if h["key"] != key]
        if os.path.exists(self._thumb_path(key)):
            os.remove(self._thumb_path(key))
        if (self.cfg.get("fixed") or {}).get("key") == key:
            self._keep({"fixed": None})
        self.state.save()
        log.info("never again: %s", key)
        events.add("rotation", "never", "never again: %s" % key)
        return await self.change()

    async def _change(self, force, what=None):
        got = await asyncio.to_thread(self.prepared, what)
        if not got:
            log.warning("nothing to show: %s", "couldn't make %s" % what if what else
                        "no source is on, or none has pictures")
            events.add(what if what in EVENT_SOURCES else "rotation", "nothing", "nothing to show: %s" % (
                "couldn't make it" if what else "no source is on, or none has pictures"))
            return False
        await self._put(*got, force=force, prepared=got[2].split(":")[0] not in OWN)
        return True

    async def _put(self, jpeg, label, key, force, prepared=False):
        """Up to the TV and shown (or ready for Art Mode); raises when the TV doesn't answer."""
        log.info("connecting to the TV for %s", label)
        async with TV(self.cfg["tv_host"], os.path.join(self.data, "token.txt")) as tv:
            art_mode = await tv.in_art_mode()
            if self.saver and not art_mode and not force:
                log.info("not in Art Mode: the screensaver is over")
                events.add("saver", "over", "the screensaver is over", why="the TV wasn't in Art Mode")
                self.saver = False
            # the same picture again (the screensaver's come round) is chosen where it is, not sent again
            old = next((u for u in reversed(self.state["uploaded"]) if u["key"] == key), None)
            if old and old["content_id"] in await tv.my_photos():
                content_id = old["content_id"]
                self.state["uploaded"].remove(old)
            else:
                content_id = await tv.upload(jpeg)
            if not content_id:
                raise RuntimeError("the TV didn't say it got the picture")
            if force and not art_mode:
                await tv.art_mode_on()
                art_mode = True
            await tv.show(content_id, now=art_mode)
            log.info("%s %s (%s)", "showing" if art_mode else "ready for Art Mode:", label, content_id)
            kind, _, day = key.partition(":")
            events.add(kind if kind in EVENT_SOURCES else "rotation", "shown" if art_mode else "ready",
                       ("showing %s" if art_mode else "ready for Art Mode (the TV isn't in it): %s") % label)
            if await tv.slideshow_on():
                log.warning("the TV's own slideshow is on and will change the picture too")
                events.add("tv", "slideshow", "the TV's own slideshow is on and will change the picture too")

            if kind == "music":
                self._keep_before()
                self.state["music_shown"] = key
            else:
                self.state.d.pop("before", None)  # something newer than what the music came in front of
            self.state["uploaded"].append({"content_id": content_id, "key": key, "at": int(time.time())})
            self.state["recent"] = (self.state["recent"] + [key])[-RECENT:]
            self.state["changed"] = time.time()
            self.state["showing"] = label
            self.state.d.pop("unseen", None)
            if kind in MADE and not art_mode:
                self._unseen(kind, "the TV isn't in Art Mode")
            if kind in MADE:
                if self.now().time() >= self._clock(kind + "_time"):
                    self.state["made"][kind] = day  # one asked for before its time doesn't use up today's
            elif kind not in OWN:
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
            if kind not in MADE and kind not in OWN:
                try:
                    self._keep_thumb(key, image.thumbnail(image.open_image(jpeg, draft=image.THUMB)))
                except Exception as e:
                    log.debug("no thumbnail for %s (%s)", key, e)
            try:
                await self.clean(tv)
            except Exception as e:  # the picture is up; what's left is cleaned next time
                log.warning("couldn't clean up (%s: %s)", type(e).__name__, e)

    def _keep_before(self):
        """What was on the wall when the music started, to come back to (only the first album's time)."""
        last = self.state["recent"][-1] if self.state["recent"] else ""
        if self.state.d.get("before") or not last or last.startswith("music:") or not os.path.exists(
                self.showing_path):
            return
        shutil.copyfile(self.showing_path, self.before_path)
        self.state["before"] = {"key": last, "label": self.state.d.get("showing")}

    async def art_mode(self):
        """Art Mode on, with the picture it has."""
        async with self.lock:
            async with TV(self.cfg["tv_host"], os.path.join(self.data, "token.txt")) as tv:
                if not await tv.in_art_mode():
                    await tv.art_mode_on()
                    log.info("Art Mode on")
                else:
                    events.add("tv", "art_mode_already", "already in Art Mode")
        return True

    # MARK: - Leaving Art Mode (AUG-1494)

    async def watch(self):
        await tvmod.watch(self.cfg["tv_host"], os.path.join(self.data, "token.txt"), self._art_event)

    async def start_saver(self, minutes=None):
        """Frame TV's screensaver started: Art Mode on, and the answer, at once (Frame TV waits a minute); then
        Stasera's pictures when that's on, until Art Mode goes off, a new one every `minutes` (else the interval)."""
        self.saver, self.saver_minutes = True, minutes
        events.add("saver", "start", "the screensaver started%s" % (", a new picture every %d min" % minutes
                                                                      if minutes else ""))
        try:
            await self.art_mode()
        except Exception as e:
            self.saver = False  # Frame TV shows its own
            events.add("saver", "failed", "no Art Mode (%s: %s): Frame TV shows its own" % (type(e).__name__, e))
            raise
        if self.wanted() == "saver":
            asyncio.create_task(self._saver_picture())
        return True

    async def _saver_picture(self):
        try:
            await self.change(what="saver")
        except Exception as e:
            log.info("no picture for the screensaver (%s: %s)", type(e).__name__, e)
            events.add("saver", "failed", "no picture (%s: %s)" % (type(e).__name__, e))

    def _seen(self, name, on):
        """The TV's power or Art Mode, as watched (AUG-1523): only a change is logged, with the command that caused
        it, or "from outside" (the remote, the motion sensor, the TV's own sleep)."""
        was = self.seen[name]
        if was == on:
            return
        self.seen[name] = on
        if on and name == "art_mode":
            self.wake.set()  # a rotation that waited for Art Mode goes on
        what = "%s_%s" % (name, "on" if on else "off")
        cause = events.cause(what)
        events.add("tv", what, SEEN[what], why=cause or ("first look" if was is None else "from outside"))
        if on is False and was is not None:
            self._went_away("the TV went off" if name == "power" else "Art Mode went off")
        elif on:
            self._seen_again(name)

    def _went_away(self, why):
        """Morgenbildet or tonight's show, with the TV off or out of Art Mode right after it (AUG-1527)."""
        kind = (self.state["recent"][-1] if self.state["recent"] else "").split(":", 1)[0]
        if kind in MADE and time.time() - self.state["changed"] < MADE_UNSEEN_MINUTES * 60:
            self._unseen(kind, why + " right after it")

    def _unseen(self, kind, why):
        """Not seen yet: it stays, and the rotation counts from when it's on the wall."""
        if self.state.d.get("unseen"):
            return
        self.state["unseen"] = kind
        self.state.save()
        name = "the morning picture" if kind == "morning" else "tonight's show"
        log.info("%s stays: %s", name, why)
        events.add(kind, "stays", "%s stays: %s" % (name, why), why=why)

    def _seen_again(self, name):
        """The TV on, or Art Mode on, with a picture not seen yet: the rotation counts from now. Art Mode on is the
        end of it; the TV on alone counts too, in case Art Mode isn't heard."""
        kind = self.state.d.get("unseen")
        if not kind:
            return
        self.state["changed"] = time.time()
        self.waiting = False
        if name == "art_mode":
            self.state.d.pop("unseen", None)
            events.add(kind, "seen", "%s is on the wall; the rotation counts from now" % (
                "the morning picture" if kind == "morning" else "tonight's show"), why="Art Mode came on again")
        self.state.save()

    def activity(self):
        """What the TV is doing, from what's been seen (AUG-1524): off, app (Frame TV or another app), art, morning,
        tonight, saver or music; unknown before the TV has been seen."""
        power, art = self.seen["power"], self.seen["art_mode"]
        if power is False:
            return "off"
        if power is None or art is None:
            return "unknown"
        if not art:
            return "app"
        if self.playing():
            return "music"
        kind = (self.state["recent"][-1] if self.state["recent"] else "").split(":", 1)[0]
        if kind in MADE:
            return kind
        return "saver" if self.saver else "art"

    def away(self):
        """Known to be off or out of Art Mode (AUG-1526): the rotation waits instead of sending pictures nobody sees.
        Not known (just started, after standby, the art channel closed) is not away."""
        return self.seen["power"] is False or self.seen["art_mode"] is False

    async def watch_power(self):
        """Asks the TV whether it's on every POWER_LOOK seconds; "off" only after two looks, since a busy TV can miss
        one."""
        host = self.cfg.get("tv_host")
        if not host:
            return
        misses = 0
        while True:
            on = await asyncio.to_thread(tvmod.powered_on, host, 5)
            misses = 0 if on else misses + 1
            if on or misses >= 2 or self.seen["power"] is None:
                self._seen("power", on)
                if not on:
                    self.seen["art_mode"] = None  # known again when the art channel answers
            await asyncio.sleep(POWER_LOOK)

    async def _art_event(self, event, data):
        off = event == "art_mode_changed" and data.get("status") == "off"
        status = data.get("value", data.get("status"))
        if (event == "art_mode_changed" or "artmode_status" in (event or "")) and status in ("on", "off"):
            self._seen("art_mode", status == "on")
        elif event == "go_to_standby":
            events.add("tv", "standby", "the TV says it's going to standby",
                       why=events.cause("power_off") or "from outside")
            if self.seen["power"]:
                self._went_away("the TV went to standby")
            self.seen["art_mode"] = None
        elif event == "channel_closed":
            self.seen["art_mode"] = None  # not heard any more, so not known
        if (off or event == "go_to_standby") and self.saver:
            self.saver = False
            log.info("the screensaver is over")
            events.add("saver", "over", "the screensaver is over",
                       why="Art Mode went off" if off else "the TV went to standby")
        if off:
            with events.because("Art Mode went off"):
                await self._back()

    async def _back(self):
        """Art Mode went off: a key on the remote opens the TV's own Art Mode menu, which has no way back but Home
        and the app. Open back_app from the options instead (Frame TV: FrameTVapp.FrameTV), when the TV is on (not going
        to standby). Without it, nothing."""
        app = (self.cfg.get("back_app") or "").strip()
        if not app or time.time() - self.back_at < 10:
            return
        self.back_at = time.time()
        await asyncio.sleep(1)
        host = self.cfg["tv_host"]
        if not await asyncio.to_thread(tvmod.powered_on, host):
            log.info("Art Mode off, and the TV isn't on: nothing opened")
            events.add("tv", "back_app_skipped", "the TV isn't on: %s not opened" % app)
            return
        try:
            ok = await asyncio.to_thread(tvmod.launch, host, app)
            log.info("Art Mode off: %s %s", "opened" if ok else "the TV didn't open", app)
            events.add("tv", "back_app" if ok else "back_app_failed", "%s %s" % (
                "opened" if ok else "the TV didn't open", app))
        except Exception as e:
            log.warning("Art Mode off, but couldn't open %s (%s: %s)", app, type(e).__name__, e)
            events.add("tv", "back_app_failed", "couldn't open %s (%s: %s)" % (app, type(e).__name__, e))

    # MARK: - Follow the music (AUG-1495)

    def playing(self):
        """The music is on and plays, or stopped less than MUSIC_GRACE ago."""
        return bool(self.cfg.get("music") and self.music and time.time() - self.music_at < MUSIC_GRACE)

    def _listen(self):
        if self.cfg.get("music_home_only", True) and not self.ha.home(self.home_entity()):
            return None
        return self.ha.playing(time.time())

    async def follow(self):
        """Looks at Home Assistant's Spotify player every few seconds while Follow the music is on, and wakes the timer
        when the song changes or the music stops."""
        if not self.ha.ready():
            log.info("Follow the music: no Home Assistant (homeassistant_api, or ha_url and ha_token)")
            return
        failing, was = False, None
        while True:
            if self.cfg.get("music"):
                try:
                    now = await asyncio.to_thread(self._listen)
                    if failing:
                        log.info("Follow the music: Home Assistant answers again")
                        events.add("music", "ha_back", "Home Assistant answers again", why="")
                    failing = False
                    if now:
                        self.music, self.music_at = now, time.time()
                except Exception as e:
                    if not failing:
                        log.info("Follow the music: Home Assistant didn't answer (%s: %s)", type(e).__name__, e)
                        events.add("music", "ha_failed", "Home Assistant didn't answer (%s: %s)" % (
                            type(e).__name__, e), why="")
                    failing = True
            key = self.music["key"] if self.playing() else None
            if key != was:
                log.info("Follow the music: %s", "%s – %s" % (self.music["title"], self.music["artist"]) if key else
                         "the music stopped")
                events.add("music", "playing" if key else "stopped", "%s – %s" % (
                    self.music["title"], self.music["artist"]) if key else "the music stopped", why="")
                self.wake.set()
                was = key
            self.listened.set()
            await asyncio.sleep(MUSIC_LOOK)

    async def _after_music(self, want):
        """The music stopped: what was on the wall before it comes back, unless Morgenbildet or tonight's show has
        its turn. Raises when the TV doesn't answer, and it's tried again."""
        self.state.d.pop("music_shown", None)
        b = self.state.d.get("before")
        if not b or want in MADE or not os.path.exists(self.before_path):
            self.state.d.pop("before", None)
            self.state.save()
            return
        with open(self.before_path, "rb") as f:
            jpeg = f.read()
        async with self.lock:
            await self._put(jpeg, b["label"], b["key"], force=False)
        log.info("the music stopped: back to %s", b["label"])
        events.add("music", "back", "back to %s" % b["label"])

    async def _tv_on(self, kind):
        """Before Morgenbildet or tonight's show: the TV on through Home Assistant when it's off and someone is home,
        once a day each. True when we turned it on today, so the picture goes to Art Mode (and on a try after that)."""
        today = self.now().date().isoformat()
        done = "tv_on" if kind == "morning" else "tv_on_" + kind  # "tv_on" from before tonight's
        if self.state["made"].get(done) == today:
            return True
        if not self.cfg.get(kind + "_tv_on", True) or not await self.tv_off() or not await self._home():
            return False
        if not await self.turn_on():
            return False
        self.state["made"][done] = today
        self.state.save()
        return True

    async def _home(self):
        """Someone at home, or the switch is off; when Home Assistant doesn't answer, yes rather than no picture."""
        if not self.cfg.get("music_home_only", True):
            return True
        entity = self.home_entity()
        try:
            home = await asyncio.to_thread(self.ha.home, entity)
        except Exception as e:
            log.info("no state for %s (%s: %s); turning the TV on anyway", entity, type(e).__name__, e)
            events.add("tv", "home_unknown", "no state for %s; turning the TV on anyway" % entity)
            return True
        if not home and self.away_logged != self.now().date():
            log.info("nobody home (%s): the TV stays off, and the picture waits until it's on", entity)
            events.add("tv", "stays_off", "nobody home (%s): the TV stays off, and the picture waits" % entity)
            self.away_logged = self.now().date()
        return home

    def home_entity(self):
        return self.cfg.get("home_entity", "zone.home")  # saved options from before 0.21.0 lack it

    async def tv_off(self):
        """Whether the TV is off, asked of the TV itself: Home Assistant's tv_entity can say "on" for a TV that's
        asleep and doesn't answer. None without tv_entity, which is what turns it on."""
        if not self.cfg.get("tv_entity") or not self.ha.ready():
            return None
        return not await asyncio.to_thread(tvmod.powered_on, self.cfg["tv_host"], 4)

    async def turn_on(self):
        """The TV on through Home Assistant, and time for Art Mode to answer. False when it couldn't."""
        entity = self.cfg.get("tv_entity")
        events.expect("power_on")
        try:
            await asyncio.to_thread(self.ha.call, "media_player", "turn_on", {"entity_id": entity})
        except Exception as e:
            log.info("couldn't turn the TV on through Home Assistant (%s: %s)", type(e).__name__, e)
            events.add("tv", "turn_on_failed", "couldn't turn the TV on through Home Assistant (%s: %s)" % (
                type(e).__name__, e))
            return False
        log.info("turned the TV on through Home Assistant (%s)", entity)
        events.add("tv", "turned_on", "the TV was off: turned it on through Home Assistant (%s)" % entity)
        await asyncio.sleep(TV_ON_WAIT)
        return True

    async def wake_up(self):
        """The page's "Turn the TV on": on through Home Assistant, then back_app (Frame TV) on the screen. Doesn't wait
        for the lock, which a sleeping TV holds."""
        entity, host = self.cfg.get("tv_entity"), self.cfg["tv_host"]
        if not entity:
            raise ValueError("tv_entity is empty in the add-on's configuration")
        if not await asyncio.to_thread(tvmod.powered_on, host):
            events.expect("power_on")
            await asyncio.to_thread(self.ha.call, "media_player", "turn_on", {"entity_id": entity})
            log.info("turned the TV on through Home Assistant (%s), from the page", entity)
            events.add("tv", "turned_on", "turned the TV on through Home Assistant (%s)" % entity)
            until = time.time() + WAKE_WAIT
            while not await asyncio.to_thread(tvmod.powered_on, host):
                if time.time() > until:
                    events.add("tv", "turn_on_failed", "the TV didn't come on")
                    raise RuntimeError("the TV didn't come on")
                await asyncio.sleep(2)
        self.retry_at = 0
        self.wake.set()  # the timer tries again now that it answers
        app = (self.cfg.get("back_app") or "").strip()
        if not app:
            return True
        self.back_at = time.time()  # coming up in Art Mode and leaving it opens the app once, not twice
        for attempt in range(3):  # just woken, the TV can say no to the first
            try:
                if await asyncio.to_thread(tvmod.launch, host, app):
                    log.info("opened %s", app)
                    events.add("tv", "back_app", "opened %s" % app)
                    return True
            except Exception as e:
                log.info("couldn't open %s yet (%s: %s)", app, type(e).__name__, e)
            await asyncio.sleep(3)
        events.add("tv", "back_app_failed", "the TV is on, but didn't open %s" % app)
        raise RuntimeError("the TV is on, but didn't open %s" % app)

    async def _nap(self, seconds):
        try:
            await asyncio.wait_for(self.wake.wait(), seconds)
        except asyncio.TimeoutError:
            pass
        self.wake.clear()

    def status(self):
        interval = self.interval()
        # None: not listed yet (or not since only 16:9 is used); 0: listed, and nothing found
        pools = {s.name: len(self.state["pools"][s.name].get("keys") or [])
                 if (self.state["pools"].get(s.name) or {}).get("wide") else None for s in self.sources}
        off = set(self.cfg.get("sources_off") or [])
        categories = []
        for c in self.categories:
            names = [s.name for s in self.sources if s.category == c]
            counts = [pools[n] for n in names if pools[n] is not None]
            categories.append({"name": c, "on": any(n not in off for n in names), "sources": names,
                               "sources_on": [n for n in names if n not in off],
                               "pictures": sum(counts) if counts else None, "unread": len(names) - len(counts)})
        fixed = self.fixed()
        # no next change while the music or a fixed picture stands, or while it waits for Art Mode
        rotating = not fixed and not self.playing() and not self.waiting
        return {"version": __version__, "showing": self.state.d.get("showing"), "changed": int(self.state["changed"]),
                "next": int(self.state["changed"] + interval) if self.state["changed"] and rotating else None,
                "interval_minutes": interval / 60, "sources": [s.name for s in self.sources],
                "source_categories": {s.name: s.category for s in self.sources},
                "pools": pools, "schedule": self.schedule(), "settings": self.settings(),
                "mode": "fixed" if fixed else "shuffle", "category": self._one_category(),
                "reading": bool(self.reading),
                "categories": categories, "fixed": fixed, "wanted": self.wanted(),
                "stasera": self.stasera.state(), "pairing": self.stasera.pairing, "busy": self.lock.locked(),
                "saver": self.saver, "showing_key": self.showing_key(), "tv_entity": bool(self.cfg.get("tv_entity")),
                "home_entity": self.home_entity(),
                "tv": {"power": self.seen["power"], "activity": self.activity(),
                       "art_mode": False if self.seen["power"] is False else self.seen["art_mode"]},
                "music": {k: self.music[k] for k in ("album", "artist", "title")}
                if self.playing() else None}

    def _one_category(self):
        """The category, when what's ticked is exactly one category's sources (for Home Assistant's select)."""
        on = {s.name for s in self.in_play()}
        for c in self.categories:
            if on == {s.name for s in self.sources if s.category == c}:
                return c
        return None

    def unlisted(self):
        """The sources never listed, or not since only 16:9 is used."""
        return [s for s in self.sources if not (self.state["pools"].get(s.name) or {}).get("wide")]

    def read_unlisted(self):
        """Lists the unlisted sources, so the page has the numbers; in the background, at the start."""
        try:
            for s in self.unlisted():
                self.pool(s)
                self.state.save()
        finally:
            self.reading.discard("*")

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
        if not image.croppable(*img.size):
            self.state["bad"].append(full)  # never drawn, and not offered again
            raise sources.Skip("%dx%d isn't close to 16:9" % img.size)
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
        not listed yet are listed in the background; "reading" says which."""
        if category not in self.categories:
            raise ValueError("no category called %s" % category)
        names = {s.name for s in self.in_play() if s.category == category}  # what's ticked
        bad = set(self.state["bad"])
        recent, seen = [], set(bad)
        for h in reversed(self.state["history"]):
            if h["key"] not in seen and h["key"].split(":", 1)[0] in names:
                seen.add(h["key"])
                recent.append({"key": h["key"], "label": h["label"].split(": ", 1)[-1]})
        keys = [name + ":" + k for name in names for k in (self.state["pools"].get(name) or {}).get("keys") or []]
        keys = [k for k in keys if k not in bad]
        unlisted = sorted(name for name in names if name not in self.state["pools"])
        if unlisted and category not in self.reading:
            self.reading.add(category)
            asyncio.get_running_loop().run_in_executor(None, self._read, category)
        return {"category": category, "off": not names, "recent": recent[:n],
                "random": [{"key": k} for k in random.sample(keys, min(n, len(keys)))], "reading": unlisted}

    async def clean(self, tv):
        """Deletes our own older uploads, keeping the newest few; never anything else in "My Photos"."""
        keep = max(1, int(self.cfg.get("keep") or 3))
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
        if self.saver and self.saver_minutes:
            return self.saver_minutes * 60
        return max(1, float(self.cfg.get("interval_minutes", 60))) * 60

    def _reason(self, want):
        """Why the timer changes the picture now, for the event log."""
        if want in MADE:
            return "%s at %s" % ("the morning picture" if want == "morning" else "tonight's show",
                                 self._clock(want + "_time").strftime("%H:%M"))
        if want == "music":
            return "Follow the music"
        return "%s, every %g min" % ("the screensaver" if want == "saver" else "the rotation", self.interval() / 60)

    async def run(self):
        if not self.cfg.get("tv_host"):
            log.error("tv_host is empty: set the TV's IP address in the add-on's configuration, then start it again")
            return
        log.info("Frame Art %s for %s, every %g min, sources: %s", __version__, self.cfg["tv_host"],
                 self.interval() / 60, ", ".join(s.name for s in self.sources) or "none")
        events.add("rotation", "started", "Frame Art %s started" % __version__, why="")
        if self.unlisted():
            self.reading.add("*")
            asyncio.get_running_loop().run_in_executor(None, self.read_unlisted)
        if self.cfg.get("music") and self.ha.ready():
            try:  # music playing through a restart: not what was before it first, then the cover again
                await asyncio.wait_for(self.listened.wait(), 30)
            except asyncio.TimeoutError:
                pass
        while True:
            wait = self.state["changed"] + self.interval() - time.time()  # the interval can change on the page
            want = self.wanted()
            if want == "music" and time.time() < self.retry_at:
                await self._nap(self.retry_at - time.time())  # a new song doesn't try a sleeping TV again sooner
                continue
            if want == "music" and self.state.d.get("music_shown") == self.music["key"]:
                await self._nap(60)  # the same song still
                continue
            if want != "music" and (self.state.d.get("music_shown") or self.state.d.get("before")):
                why, job = "the music stopped", self._after_music(want)
            elif want == "fixed" or (want in ("rotation", "saver") and wait > 0):
                await self._nap(min(wait, 60) if wait > 0 else 60)  # the API moves the time; look each minute
                continue
            elif want in ("rotation", "saver") and self.away():
                if not self.waiting:
                    self.waiting = True
                    log.info("the rotation waits for Art Mode")
                    events.add("rotation", "waiting", "waiting for Art Mode: no new picture until it's on",
                               why="the TV is off" if self.seen["power"] is False else "the TV isn't in Art Mode")
                await self._nap(60)  # woken when Art Mode comes on
                continue
            else:
                why = self._reason(want)
                if self.waiting and want in ("rotation", "saver"):
                    why = "Art Mode came on again"
                self.waiting = False
                with events.because(why):
                    woke = want in MADE and await self._tv_on(want)
                job = self.change(art_mode=woke, what=want if want in OWN else None)
            try:
                with events.because(why):
                    ok = (await job) is not False
            except Exception as e:
                # off, away, or busy with something that stops the art app (AirPlay, some apps): never interrupted
                log.info("Art Mode not answering (%s: %s); trying again in %d min", type(e).__name__, e, RETRY_MINUTES)
                events.add("tv", "not_answering", "Art Mode not answering (%s: %s); trying again in %d min" % (
                    type(e).__name__, e, RETRY_MINUTES), why=why)
                ok = False
            if not ok:
                self.retry_at = time.time() + RETRY_MINUTES * 60
                await self._nap(RETRY_MINUTES * 60)
