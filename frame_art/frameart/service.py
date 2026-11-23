"""The rotation: every interval a random picture from a random source that's on, up to the TV, shown, and our older
uploads removed. It remembers in state.json what it uploaded (only those are ever deleted), what it showed lately
and when, so a restart of the Pi or the TV picks up where it was.

Two pictures we make have a time of their own (AUG-1447): Morgenbildet, with the date and the weather, and tonight's
show from Stasera as a poster. Each has a window for every day of the week (morning_days, tonight_days); within it, it
stands on the wall instead of the rotation. Outside it, it's skipped that day.

guard() keeps Art Mode on while someone is home, except at night: sleep_entity when there is one, else from when
tonight's window ends until the morning window starts. The TV comes on when the night is over, when a window starts and
when someone comes home; it goes off when the night starts, after night_timer_minutes of Art Mode turned on at night,
and when nobody is home.

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
import copy
import datetime
import hashlib
import json
import logging
import os
import random
import shutil
import threading
import time
from zoneinfo import ZoneInfo

from . import __version__, events, i18n, image, made, music, net, sources, today as todaymod, weather
from .i18n import t
from .stasera import Stasera, Unlinked
from . import tv as tvmod
from .tv import TV

log = logging.getLogger(__name__)

PICK_TRIES = 12  # pictures tried for one change before giving up until the next
RECENT = 200  # not the same picture again within this many changes (or the whole pool, if it's smaller)
RETRY_MINUTES = 5  # TV off or away
PICK_QUIET = 5  # seconds after the TV or Art Mode comes on when the picture the TV names is not a choice in its menu
MADE_RETRY_MINUTES = 15  # Stasera didn't answer
MADE_UNSEEN_MINUTES = 10  # the TV off this soon after Morgenbildet or tonight's show: it stays until it's seen
MADE = ("morning", "tonight")
EVENT_SOURCES = ("morning", "tonight", "music", "saver")  # a picture's kind -> the event log's source; else rotation
MODES = ("shuffle", "category")  # "category" only from older callers: it becomes that category's sources
SAVER = {"watching": "watching", "wantToStart": "want_to_start"}  # Stasera's lists for the screensaver -> the heading
REPEAT_DAYS_MAX = 365  # how long "shown_at" remembers a picture
HISTORY = 100  # pictures from the rotation remembered for "Recently shown"
THUMBS = 600  # small copies kept for the add-on's page
OWN = ("saver", "music")  # pictures of the moment: not in "Recently shown", and not prepared ahead
MUSIC_LOOK = 4  # seconds between looks at Home Assistant's player
MUSIC_GRACE = 3 * 60  # paused or stopped this long, and the music has stopped
TV_ON_WAIT = 30  # seconds from Home Assistant turning the TV on until Art Mode answers
WOKE_MINUTES = 10  # this soon after the schedule turned the TV on, its picture may put it in Art Mode
GUARD_LOOK = 20  # seconds between the schedule's looks at the TV and Home Assistant
EARLY_HOURS = 2  # the TV turned on by hand this soon before the morning window: the night is over
ON_TRIES = 3  # a window's tries to turn the TV on when it doesn't come on (off the network); then not that day
TIMER_LOOK = 6 * 3600  # the TV's own Art Mode timer is looked at again this often while it's in Art Mode
DEFAULT_UNTIL = {"morning": "10:00", "tonight": "23:00"}  # a window's end before the days were set
WAKE_WAIT = 90  # seconds the page's "Turn the TV on" waits for the TV to say it's on
POWER_LOOK = 20  # seconds between asking the TV whether it's on, for the event log (AUG-1523)
TV_INFO_FRESH = 300  # seconds an answer from the art channel is good for on the TV tab
TV_INFO_WAIT = 60  # seconds the TV tab waits for the art channel
SMARTTHINGS_SECONDS = 3600  # the TV's entities in Home Assistant are looked up again this often
SEEN = {"power_on": "the TV came on", "power_off": "the TV went off", "art_mode_on": "Art Mode on",
        "art_mode_off": "Art Mode off"}


def _bool(v):
    return v if isinstance(v, bool) else None


def _hhmm(v):
    return datetime.time.fromisoformat(v).strftime("%H:%M")


def _days(v):
    """A week, Monday first: seven {on, from, until}, each window within a day."""
    if not isinstance(v, list) or len(v) != 7:
        return None
    out = []
    for d in v:
        if not isinstance(d, dict) or not isinstance(d.get("on"), bool):
            return None
        start, end = _hhmm(d["from"]), _hhmm(d["until"])
        if start >= end:
            return None
        out.append({"on": d["on"], "from": start, "until": end})
    return out


# What the add-on's page can change: name -> (default, check)
SETTINGS = {
    "interval_minutes": (60, lambda v: int(v) if 5 <= int(v) <= 1440 else None),
    "keep": (3, lambda v: int(v) if 1 <= int(v) <= 20 else None),  # our own pictures left on the TV
    "morning": (True, _bool),
    "morning_time": ("07:00", _hhmm),  # before the days: now the start of every day's window
    "tonight": (True, _bool),
    "tonight_time": ("18:00", _hhmm),
    # The week: when each picture has its window, day by day; outside it, it's skipped that day
    "morning_days": (None, _days),
    "tonight_days": (None, _days),
    "art_timer_minutes": (120, lambda v: int(v) if 0 <= int(v) <= 1440 else None),  # before 0.38.0; not used
    "night_timer_minutes": (30, lambda v: int(v) if 0 <= int(v) <= 1440 else None),  # Art Mode turned on at night; 0: never
    "away_off": (True, _bool),  # the TV off when nobody's home (home_entity), whatever it shows
    "tv_timer_off": (True, _bool),  # the TV's own Art Mode timer off, so the schedule decides
    "mode": ("shuffle", lambda v: v if v in MODES else None),
    "category": ("", lambda v: str(v).strip()),
    "categories_off": ([], lambda v: [str(c) for c in v] if isinstance(v, list) else None),  # before sources_off
    "sources_off": ([], lambda v: [str(c) for c in v] if isinstance(v, list) else None),
    # Kept for the screensaver (AUG-1494) and Follow the music (AUG-1495); the page shows them already
    # The TV turned on (Wake-on-LAN through Home Assistant) before Morgenbildet and tonight's show, when it's off
    "morning_tv_on": (True, _bool),
    "tonight_tv_on": (True, _bool),
    "screensaver": (True, _bool),  # off: Frame TV doesn't start its screensaver (it reads this from /status)
    "screensaver_stasera": (True, _bool),
    "music": (False, _bool),
    # Only when someone is home (home_entity in the options): Follow the music and turning the TV on. The name is
    # from when it was only the music; it's kept for switch.frame_art_music_home_only
    "music_home_only": (True, _bool),
    # Not the same picture again within this many days (0: only not among the last RECENT changes)
    "repeat_days": (0, lambda v: int(v) if 0 <= int(v) <= REPEAT_DAYS_MAX else None),
    "paused": (False, _bool),  # the rotation stands still; the schedule, the music and "New picture" still work
    # What Morgenbildet shows, each part on its own
    "morning_weather": (True, _bool),
    "morning_calendar": (True, _bool),
    "morning_price": (True, _bool),
    "morning_names": (True, _bool),
    "morning_stasera": (True, _bool),
}
SCHEDULE = ("interval_minutes", "morning", "morning_time", "morning_days", "tonight", "tonight_time", "tonight_days")


class State:
    def __init__(self, path):
        self.path = path
        try:
            with open(path) as f:
                self.d = json.load(f)
        except (OSError, ValueError):
            self.d = {}
        for k, v in (("uploaded", []), ("recent", []), ("bad", []), ("never", []), ("unfit", []),
                     ("pools", {}), ("changed", 0), ("made", {}), ("tried", {})):
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
        if "shown_at" not in self.state.d:  # when each picture from the rotation was last on the wall; from 0.39.0
            self.state.d["shown_at"] = {h["key"]: h["at"] for h in self.state["history"]}
        self.stasera = Stasera(cfg.get("stasera_url"), data_dir)
        self.sources = sources.from_config(cfg, self.stasera)
        self.by_name = {s.name: s for s in self.sources}
        self.categories = list(dict.fromkeys(s.category for s in self.sources))
        self.thumbs = os.path.join(data_dir, "thumbs")
        self.reading = set()  # categories whose sources are being listed for the page; "*" all of them
        self.next_path = os.path.join(data_dir, "next.jpg")
        self.showing_path = os.path.join(data_dir, "showing.jpg")
        self.lock = asyncio.Lock()  # one conversation with the TV at a time: the timer, Home Assistant, Frame TV
        self.making = asyncio.Lock()  # one change at a time, fetching included; held longer than the TV's lock
        self.nothing = ""  # why pick() found no picture
        self.relisting = set()  # the sources being listed again in the background
        self.zone = ZoneInfo(cfg.get("timezone") or os.environ.get("TZ") or "Europe/Oslo")
        self.saver = False  # Frame TV's screensaver is on, until Art Mode goes off
        self.saver_minutes = None  # how often the picture changes meanwhile, from Frame TV
        self.back_at = 0  # when Frame TV was last opened; the TV says "off" twice
        self.selecting = (None, 0)  # the picture we last asked the TV to show, and when: its image_selected is ours
        self.picked_at = 0  # when OK in the TV's Art Mode menu last asked for a new picture
        self.before_path = os.path.join(data_dir, "before.jpg")  # what was on the wall when the music started
        self.ha = music.HomeAssistant(cfg)
        self.smartthings = ([], 0)  # the TV's SmartThings entities in Home Assistant, and when they were looked up
        i18n.setup(cfg)
        self.music, self.music_at = None, 0  # what played last, and when it was last seen playing
        self.wake = asyncio.Event()  # the music changed: the timer looks at once
        self.retry_at = 0  # the TV didn't answer: a new song doesn't try again before this
        self.listened = asyncio.Event()  # the player has been looked at once since the start
        self.seen = {"power": None, "art_mode": None}  # what the TV was last seen doing; None: not known
        self.art_while_off = None  # Art Mode as heard while the TV counts as off; used if it turns out to be on
        self.waiting = False  # the rotation waits for Art Mode (AUG-1526)
        self.counts_from = 0  # the TV or Art Mode just came on: the interval counts from then, not from the change
        self.art_known = False  # Art Mode has been heard since the start: the first look isn't Art Mode coming on
        # The schedule
        self.art_since = None  # when Art Mode came on, for night_timer_minutes
        self.woke_at = 0  # when the schedule turned the TV on: its picture may put it in Art Mode
        self.was_home, self.was_asleep, self.was_night = None, None, None  # as last looked at
        self.on_since = None  # when the TV was seen coming on; None: on since before we looked
        self.on_retry_at, self.on_tries = 0, {}  # the TV didn't come on: tried again after this; tries per window
        # Wake-on-LAN didn't wake it: off the network (switched off completely), until it's seen on again. A TV that
        # only doesn't answer is in standby, which is normal
        self.gone_at = None
        self.off_retry_at = 0  # holding power didn't turn it off: not again before this
        self.turning_off_until = 0  # Art Mode going off now is ours: back_app isn't opened
        self.timer_at = 0  # when the TV's own Art Mode timer is looked at next
        self.tv_timer = None  # what it was last seen at ("off", "60" ...)
        self.tv_sensor = None  # the TV's light sensor in Art Mode, as last seen ("on"/"off")
        self.tv_info_path = os.path.join(data_dir, "tv_info.json")  # the TV tab's last answers (AUG-1722)
        self._tv_info = None  # what's in it, once read
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
        out = {k: self.cfg.get(k, default) for k, (default, _) in SETTINGS.items()}
        out.update(morning_days=self.days("morning"), tonight_days=self.days("tonight"))
        return out

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
        for kind in MADE:  # a start time from an older caller moves every day's window that it fits
            if kind + "_time" in clean and kind + "_days" not in clean and self.cfg.get(kind + "_days"):
                clean[kind + "_days"] = [dict(d, **{"from": clean[kind + "_time"]})
                                         if clean[kind + "_time"] < d["until"] else d for d in self.days(kind)]
        if ("mode" in clean or "sources_off" in clean) and self.cfg.get("fixed"):
            clean["fixed"] = None
        resumed = clean.get("paused") is False and self.cfg.get("paused")
        if clean.get("tv_timer_off") and not self.cfg.get("tv_timer_off", True):
            self.timer_at = 0  # turned on: the TV's timer and light sensor are turned off at once (in Art Mode)
        self._keep(clean)
        if resumed:  # a whole interval for what's on the wall, rather than a new picture the moment it's resumed
            self.counts_from = time.time()
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
        for i in range(8):
            w = self._window("morning", now.date() + datetime.timedelta(days=i))
            if w and w[0] > now:
                return w[0].timestamp()
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
        if self.held():
            return self.window_now()[0]
        if self.saver and self.cfg.get("screensaver_stasera", True) and self.stasera.state() == "linked":
            return "saver"
        return "rotation"

    # MARK: - Picking

    def pool(self, src):
        p = self.state["pools"].get(src.name)
        if p and p.get("wide") and src.pool_hours and p["keys"]:  # wide: listed since only 16:9 is used (0.14.0)
            if time.time() - p["at"] >= src.pool_hours * 3600 and src.name not in self.relisting:
                self.relisting.add(src.name)  # a big tree on Commons takes minutes: not while someone waits
                threading.Thread(target=self._relist, args=(src,), daemon=True).start()
            return p["keys"]
        return self._list(src)

    def _relist(self, src):
        try:
            self._list(src)
        finally:
            self.relisting.discard(src.name)

    def _list(self, src):
        p = self.state["pools"].get(src.name)
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
        """(jpeg, label, key) for a new picture, or None, and self.nothing says why."""
        bad, recent, empty = set(self.state["bad"]), self.state["recent"], set()
        for _ in range(PICK_TRIES):
            # a source is listed only when it's drawn, so a big new one doesn't hold up the others
            choices = [s for s in self.in_play() if s.name not in empty]
            if not choices:
                self.nothing = "none of the sources that are on has pictures" if self.in_play() else "no source is on"
                return None
            src = random.choice(choices)
            keys = [k for k in self.pool(src) if src.name + ":" + k not in bad]
            if not keys:
                empty.add(src.name)
                continue
            fresh = [k for k in keys if src.name + ":" + k not in recent[-min(RECENT, len(keys) - 1):]] or keys
            if self.cfg.get("repeat_days"):  # all of them shown within the days: the one shown longest ago
                shown, since = self.state["shown_at"], time.time() - self.cfg["repeat_days"] * 86400
                fresh = [k for k in fresh if shown.get(src.name + ":" + k, 0) < since] or [
                    min(fresh, key=lambda k: shown.get(src.name + ":" + k, 0))]
            key = random.choice(fresh)
            full = src.name + ":" + key
            try:
                return self.render(src, key)
            except sources.Skip as e:
                log.info("skipping %s: %s", full, e)
                self._leave_out(full, "unfit")
                bad.add(full)
            except Exception as e:
                log.warning("couldn't fetch %s: %s", full, e)
                events.add("rotation", "fetch_failed", "couldn't fetch %s: %s" % (full, e))
        self.nothing = "tried %d pictures, and none of them could be used" % PICK_TRIES
        return None

    # MARK: - The pictures we make

    def now(self):
        return datetime.datetime.now(self.zone)

    def _clock(self, name):
        try:
            return datetime.time.fromisoformat(self.cfg.get(name) or SETTINGS[name][0])
        except ValueError:
            return datetime.time.fromisoformat(SETTINGS[name][0])

    def days(self, kind):
        """The week for morning or tonight; before it was set, every day from <kind>_time to DEFAULT_UNTIL."""
        if self.cfg.get(kind + "_days"):
            return self.cfg[kind + "_days"]
        start = self._clock(kind + "_time").strftime("%H:%M")
        end = DEFAULT_UNTIL[kind] if DEFAULT_UNTIL[kind] > start else "23:59"
        return [{"on": True, "from": start, "until": end} for _ in range(7)]

    def _times(self, kind, day):
        """(start, end) of kind's window on that date as the week has it, also when it's off: the night is between."""
        d = self.days(kind)[day.weekday()]
        at = lambda hhmm: datetime.datetime.combine(day, datetime.time.fromisoformat(hhmm), tzinfo=self.zone)
        return at(d["from"]), at(d["until"])

    def _window(self, kind, day):
        """(start, end) of kind's window on that date, or None: switched off, or not that day."""
        if not self.cfg.get(kind, True) or (kind == "tonight" and self.stasera.state() != "linked"):
            return None
        if not self.days(kind)[day.weekday()]["on"]:
            return None
        return self._times(kind, day)

    def _has_sleep(self):
        return bool((self.cfg.get("sleep_entity") or "").strip())

    def night_span(self):
        """(start, end) of the schedule's night we're in, or None: from when tonight's window ends until the morning
        window starts, by the week's times (also on a day the picture is off)."""
        now = self.now()
        for day in (now.date() - datetime.timedelta(days=1), now.date()):
            start = self._times("tonight", day)[1]
            end = self._times("morning", day + datetime.timedelta(days=1))[0]
            if start <= now < end:
                return start, end
        return None

    def night(self, asleep):
        """Whether it's night: sleep_entity on, when there is one (None when it doesn't answer); else the schedule's
        night, unless the TV was turned on by hand within EARLY_HOURS of its end."""
        if self._has_sleep():
            return asleep
        span = self.night_span()
        return bool(span) and self.state.d.get("woke") != span[1].isoformat()

    def _night_began(self):
        """When this night began: when everyone fell asleep, or when tonight's window ended."""
        if self._has_sleep():
            return self.state.d.get("slept", 0)
        span = self.night_span()
        return span[0].timestamp() if span else 0

    def _morning_from(self, w):
        """When the morning picture starts: its window's start, or earlier when the night ended early (woke_at)."""
        woke = self.state.d.get("woke_at")
        at = datetime.datetime.fromtimestamp(woke, self.zone) if woke else None
        return at if at and w[0] - datetime.timedelta(hours=EARLY_HOURS) <= at < w[0] else w[0]

    def window_now(self):
        """(kind, start, end) of the picture whose time it is, or None: the morning window (from when the night ended,
        when that was early), tonight's window, and with sleep_entity tonight's show after it until everyone's asleep
        (end None then)."""
        now = self.now()
        w = self._window("morning", now.date())
        if w and self._morning_from(w) <= now < w[1]:
            return "morning", self._morning_from(w), w[1]
        w = self._window("tonight", now.date())
        if w and w[0] <= now < w[1]:
            return ("tonight",) + w
        if self._has_sleep() and self.was_asleep is False:
            for day in (now.date(), now.date() - datetime.timedelta(days=1)):
                w = self._window("tonight", day)
                morning = self._times("morning", day + datetime.timedelta(days=1))[0]
                if w and w[1] <= now < morning and self.state["made"].get("tonight") == day.isoformat() and \
                        self.state.d.get("slept", 0) < w[0].timestamp():
                    return "tonight", w[0], None
        return None

    def held(self):
        """The picture whose time it is has been on the wall: it stands, instead of the rotation, until its time is
        over. Not when there was nothing tonight."""
        w = self.window_now()
        if not w:
            return False
        day = w[1].date().isoformat()
        return self.state["made"].get(w[0]) == day and self.state["made"].get(w[0] + "_none") != day

    def due(self):
        """'tonight' or 'morning' when it's its time and it hasn't been on the wall yet, else None."""
        w = self.window_now()
        if not w or self.state["made"].get(w[0]) == w[1].date().isoformat():
            return None
        if time.time() - self.state["tried"].get(w[0], 0) < MADE_RETRY_MINUTES * 60:
            return None
        return w[0]

    def make(self, kind):
        """(jpeg, label, key) for Morgenbildet or tonight's poster, or None (and it's tried again later)."""
        now = self.now()
        today = now.date().isoformat()
        try:
            if kind == "morning":
                w = self.weather(now) if self.cfg.get("morning_weather", True) else None
                img, label = made.morning_picture(now, w, self._day(now)), "Morning picture"
            else:
                items = [i for i in self.stasera.tonight() if i.get("textlessBackdropPath") or i.get("backdropPath")]
                if not items:
                    log.info("nothing in Stasera tonight")
                    events.add(kind, "nothing", "nothing in Stasera tonight")
                    self.state["made"][kind] = self.state["made"][kind + "_none"] = today  # not again today
                    self.state.save()
                    return None
                img, label = made.poster(items[0], self.stasera), "Tonight: %s" % (items[0].get("title") or "?")
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
        ha, on = self.ha.ready(), lambda part: self.cfg.get("morning_" + part, True)
        return {"names": todaymod.names(now) if on("names") else "",
                "events": todaymod.events(self.ha, self.cfg.get("calendars") or [], now)
                if ha and on("calendar") else [],
                "shows": todaymod.shows(self.stasera, now.date())
                if on("stasera") and self.stasera.state() == "linked" else [],
                "power": todaymod.power(self.ha, self.cfg["price_entity"], now)
                if ha and on("price") and self.cfg.get("price_entity") else None}

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
        keys = ["saver:%s:%s%s" % (i.get("kind"), i.get("titleId"), ":%sx%s" % (i["seasonNumber"], i.get(
            "episodeNumber")) if i.get("kind") == "show" and i.get("seasonNumber") is not None else "") for i in items]
        recent = self.state["recent"][-(len(keys) - 1):] if len(keys) > 1 else []
        n = next((n for n, k in enumerate(keys) if k not in recent), 0)
        try:
            img = made.poster(items[n], self.stasera, t(SAVER[items[n]["list"]]))
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
        if meta and meta["key"] in self.state["bad"]:
            meta = None  # left out after it was made
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

    async def change(self, art_mode=False, what=None, join=False):
        """A new picture. With art_mode, the TV goes to Art Mode too (Home Assistant, Frame TV); the timer never does.
        what: 'morning' or 'tonight' for that one now. It ends a fixed picture (the timer doesn't change one).
        join: someone asked, and a new picture on its way is what they want: clicks don't queue up a picture each."""
        if join and self.making.locked():
            async with self.making:
                pass
            return await self.art_mode() if art_mode else True
        async with self.making:
            ok = await self._change(art_mode, what)
            if ok and self.cfg.get("fixed") and what != "music":
                self._keep({"fixed": None})
            return ok

    async def choose(self, full):
        """A picture you chose on the add-on's page: shown now, in Art Mode, standing until the next Morgenbildet."""
        src = self.source_of(full)
        if not src:
            raise ValueError("no source called %s" % full.split(":", 1)[0])
        async with self.making:
            try:
                got = await asyncio.to_thread(self.render, src, full.split(":", 1)[1])
            except sources.Skip as e:
                self._leave_out(full, "unfit")
                self.state.save()
                raise ValueError("that picture can't be used (%s)" % e)
            async with self.lock:
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

    async def never(self, key=None):
        """A picture is never drawn again (a backdrop with a logo that wasn't marked, a picture you don't like): what's
        on the wall, or key, chosen on the add-on's page. If it's on the wall, another one comes."""
        showing = self.showing_key()
        key = key or showing
        if not key or not self.source_of(key):
            raise ValueError("only a picture from the sources can be left out")
        self._leave_out(key, "never")
        self.state["history"] = [h for h in self.state["history"] if h["key"] != key]
        if os.path.exists(self._thumb_path(key)):
            os.remove(self._thumb_path(key))
        if (self.cfg.get("fixed") or {}).get("key") == key:
            self._keep({"fixed": None})
        self.state.save()
        log.info("never again: %s", key)
        events.add("rotation", "never", "never again: %s" % key)
        return await self.change(join=True) if key == showing else True

    async def _change(self, force, what=None):
        got = await asyncio.to_thread(self.prepared, what)
        if not got:
            log.warning("nothing to show: %s", "couldn't make %s" % what if what else self.nothing)
            events.add(what if what in EVENT_SOURCES else "rotation", "nothing", "nothing to show: %s" % (
                "couldn't make it" if what else self.nothing))
            return False
        async with self.lock:
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
            self.selecting = (content_id, time.time())
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
                w = self.window_now()
                if w and w[0] == kind:
                    self.state["made"][kind] = day  # one asked for before its time doesn't use up today's
            elif kind not in OWN:
                self.state["history"] = (self.state["history"] + [{"key": key, "label": label,
                                                                    "at": int(time.time())}])[-HISTORY:]
                old = time.time() - REPEAT_DAYS_MAX * 86400
                self.state["shown_at"] = {k: at for k, at in self.state["shown_at"].items() if at >= old}
                self.state["shown_at"][key] = int(time.time())
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
        it, or "from outside" (the remote, the motion sensor, the TV's own sleep). A TV in standby wakes for a minute
        now and then and says it's in Art Mode, so what's heard while it's off waits until it's seen to be on."""
        if name == "art_mode" and self.seen["power"] is False:
            if self.art_while_off != on:
                log.info("the TV says Art Mode is %s while it counts as off", "on" if on else "off")
            self.art_while_off = on
            return
        was = self.seen[name]
        if was == on:
            return
        self.seen[name] = on
        # Art Mode coming on (not the first look, not the art channel opening again) or the TV coming on
        fresh = on and ((name == "art_mode" and self.art_since is None and self.art_known)
                        or (name == "power" and was is False))
        if name == "art_mode":
            self.art_since = (self.art_since or time.time()) if on else None
            self.art_known = True
        elif not on:
            self.art_since, self.timer_at = None, 0
        if fresh:
            self._count_from_now("Art Mode came on" if name == "art_mode" else "the TV came on")
        if on:
            self.wake.set()  # a rotation that waited for Art Mode, or music that waited for the TV, goes on
        what = "%s_%s" % (name, "on" if on else "off")
        cause = events.cause(what)
        why = cause or ("first look" if was is None else "from outside")
        events.add("tv", what, SEEN[what], why=why)
        log.info("%s (%s)", SEEN[what], why)
        if on and name == "power":
            self.gone_at = None
        if name == "power" and on and was is False:
            self.on_since = time.time()
            if not cause:
                self._on_by_hand()
        if on is False and was is not None:
            self._went_away("the TV went off" if name == "power" else "Art Mode went off")
            if name == "power":
                self._saver_over("the TV went off")
        elif on:
            self._seen_again(name)
        if name == "power" and on and self.art_while_off is not None:
            art, self.art_while_off = self.art_while_off, None
            self._seen("art_mode", art)

    def _on_by_hand(self):
        """The TV turned on by hand within EARLY_HOURS of the end of the schedule's night: the night is over, and the
        morning picture comes now."""
        if self._has_sleep():
            return
        span = self.night_span()
        if not span or self.now() < span[1] - datetime.timedelta(hours=EARLY_HOURS):
            return
        self.state["woke"], self.state["woke_at"] = span[1].isoformat(), time.time()
        self.state.save()
        log.info("the TV was turned on before %s: the night is over", span[1].strftime("%H:%M"))
        events.add("tv", "night_over", "the night is over: the TV was turned on before %s" % span[1].strftime(
            "%H:%M"), why="the TV was turned on by hand")
        self.wake.set()

    def _count_from_now(self, why):
        """The picture on the wall gets a whole interval from now, rather than changing the moment it's seen."""
        self.counts_from = time.time()
        if self.waiting:
            self.waiting = False
            events.add("rotation", "counts", "a new picture in %g min" % (self.interval() / 60), why=why)

    def change_at(self):
        """When the rotation changes the picture next."""
        return max(self.state["changed"], self.counts_from) + self.interval()

    def _saver_over(self, why):
        if self.saver:
            self.saver = False
            log.info("the screensaver is over")
            events.add("saver", "over", "the screensaver is over", why=why)

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
            if on and not self._mac():
                await self._learn_mac()  # for Wake-on-LAN, before it's needed
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
            log.info("the TV says it's going to standby (%s)", events.cause("power_off") or "from outside")
            events.add("tv", "standby", "the TV says it's going to standby",
                       why=events.cause("power_off") or "from outside")
            if self.seen["power"]:
                self._went_away("the TV went to standby")
            self.seen["art_mode"], self.art_while_off = None, None  # the screensaver goes on: the TV can stay on
        elif event == "channel_closed":
            self.seen["art_mode"], self.art_while_off = None, None  # not heard any more, so not known
        elif event == "image_selected":
            self._picked(data)
        if off:
            self._saver_over("Art Mode went off")
            with events.because("Art Mode went off"):
                await self._back()

    def _picked(self, data):
        """A picture was chosen on the TV. The remote's keys in Art Mode only open the TV's own menu and say nothing;
        OK on a picture there is the one thing we hear, so it means "New picture". Our own choices are left alone."""
        content_id, at = self.selecting
        if time.time() - at < 10 or (data.get("content_id") == content_id and time.time() - at < 60):
            return
        if data.get("is_shown") == "No" or time.time() - self.picked_at < 5 or self.making.locked():
            return
        # The TV says which picture it shows as it wakes or Art Mode comes on; nobody chose it. Waking, it says so
        # before the power look has seen it on.
        if self.seen["power"] is not True:
            log.info("the TV names a picture while it counts as off: not OK in the menu")
            return
        quiet = [t for t in (self.art_since, self.on_since) if t and time.time() - t < PICK_QUIET]
        if quiet:
            log.info("the TV names a picture as it comes on: not OK in the menu")
            return
        self.picked_at = time.time()
        log.info("OK in the TV's Art Mode menu: a new picture")
        with events.because("OK in the TV's Art Mode menu"):
            events.add("tv", "picked", "a picture chosen in the TV's Art Mode menu: a new picture instead")
            task = asyncio.create_task(self.change(join=True))
        task.add_done_callback(lambda t: t.cancelled() or not t.exception() or log.warning(
            "the new picture after OK failed (%s)", t.exception()))
        self.picking = task  # kept, so it isn't collected while it runs

    async def _back(self):
        """Art Mode went off: a key on the remote opens the TV's own Art Mode menu, which has no way back but Home
        and the app. Open back_app from the options instead (Frame TV: FrameTVapp.FrameTV), when the TV is on (not going
        to standby). Without it, nothing."""
        app = (self.cfg.get("back_app") or "").strip()
        if not app or time.time() - self.back_at < 10 or time.time() < self.turning_off_until:
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
            if want in MADE and self.held():  # it stands: on the wall again, made anew
                self.state["made"].pop(want, None)
            self.state.d.pop("before", None)
            self.state.save()
            return
        with open(self.before_path, "rb") as f:
            jpeg = f.read()
        async with self.lock:
            await self._put(jpeg, b["label"], b["key"], force=False)
        log.info("the music stopped: back to %s", b["label"])
        events.add("music", "back", "back to %s" % b["label"])

    def home_entity(self):
        return self.cfg.get("home_entity", "zone.home")  # saved options from before 0.21.0 lack it

    async def tv_off(self):
        """Whether the TV is off, asked of the TV itself. None while Home Assistant, which turns it on, doesn't
        answer."""
        if not self.ha.ready():
            return None
        return not await asyncio.to_thread(tvmod.powered_on, self.cfg["tv_host"], 4)

    def _mac(self):
        """The TV's MAC address, as the TV said it on port 8001 (wifiMac), or None."""
        if self._tv_info is None:
            self._tv_info_saved()
        return ((self._tv_info.get("device") or {}).get("device") or {}).get("wifiMac") or None

    async def _learn_mac(self):
        """Asks the TV about itself and keeps the answer (the TV tab shows it too); the MAC address, or None."""
        try:
            got = self._tv_info_saved()
            got["device"] = await asyncio.to_thread(tvmod.device, self.cfg["tv_host"], 5)
            got["device_at"] = time.time()
            self._keep_tv_info(got)
        except Exception as e:
            log.info("couldn't ask the TV for its MAC address (%s: %s)", type(e).__name__, e)
        return self._mac()

    async def _wol(self):
        """Wake-on-LAN to the TV, sent by Home Assistant: the add-on's own network doesn't reach the home network's
        broadcast. Raises when it can't; the MAC address when it's sent. Tested 17.11.2026: on from standby in a
        second."""
        mac = self._mac() or await self._learn_mac()
        if not mac:
            raise RuntimeError("the TV's MAC address isn't known yet; it's read from the TV the first time it answers")
        try:
            await asyncio.to_thread(self.ha.call, "wake_on_lan", "send_magic_packet", {"mac": mac})
        except Exception as e:
            raise RuntimeError("Home Assistant couldn't send Wake-on-LAN; is the Wake on LAN integration added? "
                               "(%s: %s)" % (type(e).__name__, e))
        return mac

    async def turn_on(self):
        """The TV on with Wake-on-LAN, and time for Art Mode to answer. False when it couldn't."""
        events.expect("power_on")
        try:
            mac = await self._wol()
        except Exception as e:
            log.info("couldn't turn the TV on (%s)", e)
            events.add("tv", "turn_on_failed", "couldn't turn the TV on (%s)" % e)
            return False
        log.info("turned the TV on with Wake-on-LAN (%s)", mac)
        events.add("tv", "turned_on", "the TV was off: turned it on with Wake-on-LAN")
        await asyncio.sleep(TV_ON_WAIT)
        return True

    # MARK: - The schedule: the TV on and off

    async def guard(self):
        """The schedule's own work, every GUARD_LOOK seconds: Art Mode while someone is home, except at night. The TV
        on when the night is over, when a window starts and when someone comes home (also at night); off when the
        night starts, after night_timer_minutes of Art Mode turned on at night, and when nobody is home; and the TV's
        own Art Mode timer off. At night it only turns the TV off from Art Mode: something that plays is left alone."""
        if not self.cfg.get("tv_host"):
            return
        while True:
            try:
                await self._guard()
            except Exception as e:
                log.warning("the schedule: %s: %s", type(e).__name__, e)
            await asyncio.sleep(GUARD_LOOK)

    async def _guard(self):
        home = await asyncio.to_thread(self._is_home)
        asleep = await asyncio.to_thread(self._is_asleep)
        if asleep is not None and asleep != self.was_asleep and self.was_asleep is not None:
            self.state["slept" if asleep else "woke_at"] = time.time()
            self.state.save()
        if asleep is not None:
            self.was_asleep = asleep
        night = self.night(asleep)
        arrived = self.was_home is False and home is True
        night_over = self.was_night is True and night is False
        if home is not None:
            self.was_home = home
        if night is not None:
            if night != self.was_night and self.was_night is not None:
                log.info("the night %s", "starts" if night else "is over")
                events.add("tv", "night" if night else "day", "the night starts" if night else "the night is over",
                           why=self.cfg.get("sleep_entity") or "the schedule")
            self.was_night = night
        w = self.window_now()
        kind = w[0] if w else None

        if self.seen["power"]:
            why, anything = None, False
            if home is False and self.cfg.get("away_off", True):
                why, anything = "nobody home (%s)" % self.home_entity(), True
            elif night and self.seen["art_mode"]:
                why = self._night_off()
            if why and time.time() >= self.off_retry_at:
                await self.turn_off(why, anything)
                return
            if self.seen["art_mode"] and time.time() >= self.timer_at:
                await self._tv_timer()

        if home is not True or time.time() < self.on_retry_at:
            return
        why = None
        if arrived:
            why = "someone came home"
        elif night is not False:
            return
        elif kind and self.cfg.get(kind + "_tv_on", True) and \
                self.state["made"].get("on_" + kind) != w[1].date().isoformat():
            name = "the morning picture" if kind == "morning" else "tonight's show"
            why = "%s, %s–%s" % (name, w[1].strftime("%H:%M"), w[2].strftime("%H:%M") if w[2] else "")
        elif night_over and self.cfg.get("morning_tv_on", True):
            why = "the night is over"
        if why:
            with events.because(why):
                await self._wake_for(kind, w[1].date().isoformat() if w else self.now().date().isoformat())

    def _night_off(self):
        """Why the TV goes off from Art Mode at night, or None: it's been on since before the night began, or Art
        Mode turned on at night has had night_timer_minutes."""
        if self.on_since is None or self.on_since < self._night_began():
            return "the night has begun"
        minutes = int(self.cfg.get("night_timer_minutes", SETTINGS["night_timer_minutes"][0]))
        since = self.art_since or self.on_since
        if minutes and time.time() - since >= minutes * 60:
            return "Art Mode has been on for %d min at night" % minutes
        return None

    def _is_home(self):
        """Someone home, from home_entity (always without one); None when Home Assistant doesn't answer."""
        if not self.ha.ready():
            return None
        try:
            return self.ha.home(self.home_entity())
        except Exception:
            return None

    def _is_asleep(self):
        """sleep_entity is on; False without one, None when Home Assistant doesn't answer."""
        entity = (self.cfg.get("sleep_entity") or "").strip()
        if not entity:
            return False
        if not self.ha.ready():
            return None
        try:
            return self.ha.state(entity)["state"] == "on"
        except Exception:
            return None

    async def _wake_for(self, kind, today):
        """The TV on, when it's off: then kind's picture (the timer shows it), or Art Mode with what's on the wall.
        kind None: someone came home, or the night is over, outside the windows."""
        done = "on_" + kind if kind else None
        off = await self.tv_off()
        if off is None:
            return
        if not off:  # on already: whatever it shows stays, and the window doesn't turn it on later
            if done:
                self.state["made"][done] = today
                self.state.save()
            return
        if not await self.turn_on():
            self.on_retry_at = time.time() + RETRY_MINUTES * 60
            return
        on = False
        for _ in range(10):
            on = await asyncio.to_thread(tvmod.powered_on, self.cfg["tv_host"], 4)
            if on:
                break
            await asyncio.sleep(3)
        if not on:
            tries = self.on_tries[(kind, today)] = self.on_tries.get((kind, today), 0) + 1
            last = tries >= ON_TRIES
            self.gone_at = time.time()
            log.info("the TV didn't come on (%d of %d)", tries, ON_TRIES)
            events.add("tv", "turn_on_failed", "the TV didn't come on: it's off the network; %s" % (
                "not trying again now" if last else "trying again in %d min" % RETRY_MINUTES))
            if last and done:
                self.state["made"][done] = today
                self.state.save()
            self.on_retry_at = time.time() + RETRY_MINUTES * (6 if last else 1) * 60
            return
        if done:
            self.state["made"][done] = today
            self.state.save()
        self.woke_at, self.retry_at = time.time(), 0
        if not self.due():  # nothing new to show: Art Mode with what it has
            try:
                await self.art_mode()
            except Exception as e:
                log.info("no Art Mode after turning the TV on (%s: %s)", type(e).__name__, e)
        self.wake.set()  # the timer shows the picture now

    async def turn_off(self, why, anything=False):
        """The TV off: from Art Mode only, unless anything (nobody's home)."""
        host = self.cfg["tv_host"]
        async with self.lock:
            if anything:
                self.turning_off_until = time.time() + 30
                with events.because(why):
                    await TV(host, os.path.join(self.data, "token.txt")).power_off()
            else:
                async with TV(host, os.path.join(self.data, "token.txt")) as tv:
                    if not await tv.in_art_mode():
                        self._seen("art_mode", False)
                        return False
                    self.turning_off_until = time.time() + 30
                    with events.because(why):
                        await tv.power_off()
        log.info("turned the TV off: %s", why)
        events.add("tv", "turned_off", "turned the TV off%s: %s" % ("" if anything else " from Art Mode", why),
                   why=why)
        for _ in range(10):
            await asyncio.sleep(3)
            if not await asyncio.to_thread(tvmod.powered_on, host, 4):
                return True
        log.info("the TV is still on after holding power")
        events.add("tv", "turn_off_failed", "the TV is still on after holding power; trying again in %d min" %
                   RETRY_MINUTES, why=why)
        self.off_retry_at = time.time() + RETRY_MINUTES * 60
        return False

    async def power_off(self):
        """The TV off from the page or Home Assistant, whatever it shows; the schedule turns it on again only when
        someone comes home, a window starts or the night is over."""
        if not await asyncio.to_thread(tvmod.powered_on, self.cfg["tv_host"], 4):
            return True
        return await self.turn_off(events.why() or "asked to", anything=True)

    async def _tv_timer(self):
        """The TV's own Art Mode timer ("Sleep After") and its light sensor off, with tv_timer_off, so the schedule
        decides; read either way for the page. The light sensor puts the TV in standby within a minute in a dark room,
        such as when the morning picture turns it on at 06:00 in winter."""
        self.timer_at = time.time() + 600  # until it answers
        off = self.cfg.get("tv_timer_off", True)
        async with self.lock:
            async with TV(self.cfg["tv_host"], os.path.join(self.data, "token.txt")) as tv:
                value, valid = await tv.motion_timer()
                if off and value != "off" and "off" in valid:
                    await tv.set_motion_timer("off")
                    log.info("the TV's own Art Mode timer was %s; turned it off", value)
                    events.add("tv", "tv_timer_off", "the TV's own Art Mode timer was %s min: turned it off, so the "
                               "schedule decides" % value, why="")
                    value = "off"
                self.tv_timer = value
                try:
                    sensor = await tv.light_sensor()
                except Exception as e:  # a TV without one
                    log.info("the TV's light sensor: %s: %s", type(e).__name__, e)
                    sensor = None
                if off and sensor == "on":
                    await tv.set_light_sensor("off")
                    log.info("the TV's light sensor was on; turned it off")
                    events.add("tv", "tv_sensor_off", "the TV's light sensor was on (standby in a dark room): turned "
                               "it off, so the schedule decides", why="")
                    sensor = "off"
                self.tv_sensor = sensor
                try:  # all of them, for the TV tab and Home Assistant: changed in the TV's menu, they're seen here
                    self._keep_art_settings(await tv._ask(tv.art_settings, wait=15, tries=2))
                except Exception as e:
                    log.info("the TV's Art Mode settings: %s: %s", type(e).__name__, e)
        self.timer_at = time.time() + TIMER_LOOK

    async def wake_up(self):
        """The page's "Turn the TV on": on with Wake-on-LAN, then back_app (Frame TV) on the screen. Also when the TV
        didn't answer: in standby it often doesn't, and it wakes all the same. Doesn't wait for the lock, which a
        sleeping TV holds."""
        host = self.cfg["tv_host"]
        if not await asyncio.to_thread(tvmod.powered_on, host):
            events.expect("power_on")
            try:
                mac = await self._wol()
            except Exception as e:
                events.add("tv", "turn_on_failed", "couldn't turn the TV on (%s)" % e)
                raise
            log.info("turned the TV on with Wake-on-LAN (%s), from the page", mac)
            events.add("tv", "turned_on", "turned the TV on with Wake-on-LAN")
            until = time.time() + WAKE_WAIT
            while not await asyncio.to_thread(tvmod.powered_on, host):
                if time.time() > until:
                    self.gone_at = time.time()
                    events.add("tv", "turn_on_failed", "the TV didn't come on: it's off the network")
                    raise RuntimeError("The TV didn't come on: it's off the network (switched off completely). Turn "
                                       "it on with the remote")
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

    # MARK: - The TV tab (AUG-1722)

    def _tv_info_saved(self):
        """A copy of the last answers, to change and keep."""
        if self._tv_info is None:
            try:
                with open(self.tv_info_path) as f:
                    self._tv_info = json.load(f)
            except (OSError, ValueError):
                self._tv_info = {}
        return copy.deepcopy(self._tv_info)

    def off_reason(self):
        """Why the TV last went off, as it says itself (POWER_KEY, ART_APP_TO_SUSPEND...), from Frame TV's service
        (AUG-1728); None before it has said."""
        if self._tv_info is None:
            self._tv_info_saved()
        return ((self._tv_info.get("report") or {}).get("settings") or {}).get("db/sp-kpi/power_off_reason")

    def art_settings(self):
        """The TV's Art Mode settings as last read: {item: value}, for Home Assistant."""
        if self._tv_info is None:
            self._tv_info_saved()
        return {x.get("item"): str(x.get("value")) for x in ((self._tv_info.get("art") or {}).get("settings") or [])
                if isinstance(x, dict)}

    def _keep_art_settings(self, settings):
        if not isinstance(settings, list):
            return
        got = self._tv_info_saved()
        got.setdefault("art", {})["settings"] = settings
        got["art_at"] = time.time()
        self._keep_tv_info(got)

    async def tv_info(self, fresh=False):
        """What the TV says about itself, its apps and Art Mode, for the TV tab. Each part is kept in tv_info.json with
        when it was read, so the tab has something while the TV is off. fresh: the TV is asked first; the art channel
        only when the TV is on, nobody else is talking to it, and the last answer is older than TV_INFO_FRESH."""
        got = self._tv_info_saved()
        host = self.cfg.get("tv_host")
        answer = None  # whether the TV answered now; None: not asked
        if fresh and host:
            now = time.time()
            try:
                got["device"] = await asyncio.to_thread(tvmod.device, host, 5)
                got["device_at"] = now
                answer = True
            except Exception:
                answer = False
            on = answer and (got["device"].get("device") or {}).get("PowerState") == "on"
            if on:
                back = (self.cfg.get("back_app") or "").strip()
                ids = ((back,) if back and back not in tvmod.APPS else ()) + tvmod.APPS
                found = await asyncio.gather(*[asyncio.to_thread(tvmod.app_state, host, a) for a in ids],
                                             return_exceptions=True)
                got["apps"] = [a for a in found if isinstance(a, dict)]
                got["apps_at"] = now
            if on:
                try:
                    got["volume"] = await asyncio.to_thread(tvmod.volume, host)
                    got["volume_at"] = now
                except Exception as e:
                    log.info("the TV tab: no volume over UPnP (%s: %s)", type(e).__name__, e)
            name = ((got.get("device") or {}).get("device") or {}).get("name")
            if self.ha.ready() and (name or self.cfg.get("smartthings_entity")):
                try:
                    got["ha"] = await asyncio.to_thread(self._smartthings, name, now)
                    got["ha_at"] = now
                except Exception as e:
                    log.info("the TV tab: nothing from SmartThings in Home Assistant (%s: %s)", type(e).__name__, e)
            if on and now - got.get("art_at", 0) > TV_INFO_FRESH and not self.lock.locked():
                try:
                    async with self.lock:
                        async with TV(host, os.path.join(self.data, "token.txt")) as tv:
                            got["art"] = await asyncio.wait_for(tv.info(), TV_INFO_WAIT)
                    got["art_at"] = time.time()
                    got.pop("art_error", None)
                except Exception as e:
                    log.info("the TV tab: the art channel didn't answer (%s: %s)", type(e).__name__, e)
                    got["art_error"] = str(e) or type(e).__name__
            self._keep_tv_info(got)
        ours = {u["content_id"] for u in self.state["uploaded"]}
        photos = (got.get("art") or {}).get("my_photos")
        current = ((got.get("art") or {}).get("current") or {}).get("content_id")
        newest = self.state["uploaded"][-1]["content_id"] if self.state["uploaded"] else None
        last = {}
        for e in events.since(0, None, events.LIMIT)[0]:
            if e["source"] == "tv" and e["kind"] in ("power_on", "power_off", "standby", "art_mode_on", "art_mode_off"):
                last[e["kind"]] = e["at"]
        return dict(got, answer=answer, gone_at=self.gone_at, busy=self.lock.locked(), app=(self.cfg.get("back_app") or "").strip(),
                    tv_timer_off=self.cfg.get("tv_timer_off", True),
                    power=self.seen["power"], art_mode=False if self.seen["power"] is False else self.seen["art_mode"],
                    last=last,
                    ours=None if photos is None else len([p for p in photos if p in ours]),
                    current_ours=current in ours,
                    current_label=self.state.d.get("showing") if current and current == newest else None)

    def _smartthings(self, name, now):
        """What Home Assistant's SmartThings integration knows about the TV (AUG-1728): picture and sound mode,
        volume, source and power. The TV is smartthings_entity, or else the media_player named like the TV
        (its name on port 8001); the rest are that device's entities."""
        entities, at = self.smartthings
        if not entities or now - at > SMARTTHINGS_SECONDS:
            player = (self.cfg.get("smartthings_entity") or "").strip()
            if not player:
                states = json.loads(self.ha.get("/api/states", timeout=30))
                named = [x["entity_id"] for x in states if x["entity_id"].startswith("media_player.")
                         and (x.get("attributes") or {}).get("friendly_name") == name]
                if not named:
                    raise LookupError("no media_player named %r" % name)
                player = named[0]
            entities = json.loads(self.ha.template("{{ device_entities(device_id(%s)) | list | tojson }}"
                                                   % json.dumps(player))) or [player]
            self.smartthings = (entities, now)
        out = {}
        for entity in entities:
            s = json.loads(self.ha.get("/api/states/" + entity))
            a, state = s.get("attributes") or {}, s.get("state")
            known = state not in ("unknown", "unavailable", None, "")
            if entity.startswith("media_player."):
                out["entity"] = entity
                out["state"] = state
                if a.get("volume_level") is not None:
                    out["volume"] = round(a["volume_level"] * 100)
                out.update({k: a[v] for k, v in (("muted", "is_volume_muted"), ("source", "source"),
                                                 ("sound_mode", "sound_mode"), ("sound_modes", "sound_mode_list"))
                            if a.get(v) is not None})
            elif entity.startswith("select.") and entity.endswith("picture_mode"):
                out["picture_mode"] = state if known else None
                out["picture_modes"] = a.get("options")
            elif entity.startswith("sensor.") and known and a.get("device_class") == "power":
                out["power_w"] = float(state)
                period = [a.get("power_consumption_start"), a.get("power_consumption_end")]
                try:
                    period = [datetime.datetime.fromisoformat(x.replace("Z", "+00:00")) for x in period]
                    out["period_hours"] = (period[1] - period[0]).total_seconds() / 3600
                except (AttributeError, TypeError, ValueError):
                    pass
            elif entity.startswith("sensor.") and known and entity.endswith("energy_difference"):
                out["period_kwh"] = float(state)
                out["period_at"] = s.get("last_updated")
        # Samsung's TVs often say 0 W; the energy used in the last report period (15 minutes) says more
        if not out.get("power_w") and out.get("period_kwh") is not None:
            out["power_w"] = round(out["period_kwh"] / (out.get("period_hours") or 0.25) * 1000)
            out["power_averaged"] = True
        return out

    def tv_report(self, report):
        """What Frame TV read on the TV itself (firmware, Tizen, memory, storage, Wi-Fi), sent when it starts and every
        hour; for the TV tab, since the TV's REST API says "Unknown" for the firmware. With Frame TV's service beside it
        (AUG-1728), also settings: the TV's own ECO, power and HDMI-CEC settings, by their vconf keys."""
        if not isinstance(report, dict) or len(json.dumps(report)) > 10000:
            raise ValueError("send a JSON object (at most 10 kB)")
        got = self._tv_info_saved()
        got["report"], got["report_at"] = report, time.time()
        self._keep_tv_info(got)

    def _keep_tv_info(self, got):
        self._tv_info = got
        try:
            tmp = self.tv_info_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(got, f, indent=1)
            os.replace(tmp, self.tv_info_path)
        except OSError as e:
            log.warning("couldn't keep the TV tab's answers (%s)", e)

    async def set_tv_settings(self, changes):
        """The TV's own Art Mode settings, from the TV tab: {name: value}, checked against what the TV said they can
        be. Raises ValueError on a bad one, and RuntimeError when the TV is off. Sleep After and the light sensor are
        Frame Art's while tv_timer_off is on."""
        if not isinstance(changes, dict) or not changes:
            raise ValueError("send a JSON object")
        got = self._tv_info_saved()
        known = {x.get("item"): x for x in ((got.get("art") or {}).get("settings") or []) if isinstance(x, dict)}
        clean = {}
        for name, value in changes.items():
            if name not in tvmod.ART_SETTINGS:
                raise ValueError("unknown TV setting %s" % name)
            if name in ("motion_timer", "brightness_sensor_setting") and self.cfg.get("tv_timer_off", True):
                raise ValueError("%s is kept off by Frame Art while tv_timer_off is on" % name)
            value, x = str(value).strip(), known.get(name) or {}
            if name == "brightness_sensor_setting":
                ok = value in ("on", "off")
            elif x.get("valid_values"):
                ok = value in [str(v) for v in x["valid_values"]]
            elif "min" in x and "max" in x:
                try:
                    ok = int(x["min"]) <= int(value) <= int(x["max"])
                except ValueError:
                    ok = False
            else:
                raise ValueError("the TV hasn't said what %s can be yet; open the TV tab with the TV on" % name)
            if not ok:
                raise ValueError("bad value for %s: %r" % (name, value))
            clean[name] = value
        host = self.cfg["tv_host"]
        if not await asyncio.to_thread(tvmod.powered_on, host, 5):
            raise RuntimeError("the TV is off")
        async with self.lock:
            async with TV(host, os.path.join(self.data, "token.txt")) as tv:
                settings = None
                for name, value in clean.items():
                    was = (known.get(name) or {}).get("value")
                    settings = await tv.set_art_setting(name, value)
                    now = next((str(x.get("value")) for x in settings if x.get("item") == name), None)
                    log.info("the TV's %s: %s -> %s", name, was, now)
                    events.add("tv", "art_setting", "%s: %s → %s" % (name, was, now))
                    if now != value:
                        raise RuntimeError("the TV kept %s at %s" % (name, now))
        self._keep_art_settings(settings)
        for x in settings:
            if x.get("item") == "motion_timer":
                self.tv_timer = str(x.get("value"))
            elif x.get("item") == "brightness_sensor_setting":
                self.tv_sensor = str(x.get("value"))
        return await self.tv_info()

    async def _nap(self, seconds):
        try:
            await asyncio.wait_for(self.wake.wait(), seconds)
        except asyncio.TimeoutError:
            pass
        self.wake.clear()

    def _leave_out(self, full, why):
        """Never drawn again: 'never' is the owner's choice, 'unfit' a picture that can't be used. Both are in `bad`."""
        for k in ("bad", why):
            if full not in self.state[k]:
                self.state[k].append(full)

    def status(self):
        interval = self.interval()
        # None: not listed yet (or not since only 16:9 is used); 0: listed, and nothing found
        pools = {s.name: len(self.state["pools"][s.name].get("keys") or [])
                 if (self.state["pools"].get(s.name) or {}).get("wide") else None for s in self.sources}
        off = set(self.cfg.get("sources_off") or [])
        # hidden: the owner's choice; seen: pictures that have been on the wall, plus the hidden; unfit: unusable
        left_out = {s.name: {"hidden": 0, "seen": 0, "unfit": 0} for s in self.sources}
        for field, keys in (("seen", set(self.state["shown_at"]) | set(self.state["never"])),
                            ("hidden", set(self.state["never"])), ("unfit", set(self.state["unfit"]))):
            for key in keys:
                name = key.split(":", 1)[0]
                if name in left_out:
                    left_out[name][field] += 1
        categories = []
        for c in self.categories:
            names = [s.name for s in self.sources if s.category == c]
            counts = [pools[n] for n in names if pools[n] is not None]
            categories.append({"name": c, "on": any(n not in off for n in names), "sources": names,
                               "sources_on": [n for n in names if n not in off],
                               "pictures": sum(counts) if counts else None, "unread": len(names) - len(counts),
                               **{f: sum(left_out[n][f] for n in names) for f in ("hidden", "seen", "unfit")}})
        fixed = self.fixed()
        # no next change while the music or a fixed picture stands, or while it waits for Art Mode
        rotating = not fixed and not self.playing() and not self.waiting and not self.cfg.get("paused")
        return {"version": __version__, "showing": self.state.d.get("showing"), "changed": int(self.state["changed"]),
                "next": int(self.change_at()) if self.state["changed"] and rotating else None,
                "interval_minutes": interval / 60, "sources": [s.name for s in self.sources],
                "source_categories": {s.name: s.category for s in self.sources},
                "pools": pools, "left_out": left_out, "schedule": self.schedule(), "settings": self.settings(),
                "mode": "fixed" if fixed else "shuffle", "category": self._one_category(),
                "reading": bool(self.reading),
                "categories": categories, "fixed": fixed, "wanted": self.wanted(),
                "stasera": self.stasera.state(), "pairing": self.stasera.pairing,
                "busy": self.making.locked() or self.lock.locked(),
                "saver": self.saver, "showing_key": self.showing_key(),
                "home_entity": self.home_entity(), "sleep_entity": self.cfg.get("sleep_entity") or "",
                "tv_timer": self.tv_timer, "tv_sensor": self.tv_sensor,
                "window": {"kind": w[0], "from": w[1].strftime("%H:%M"),
                           "until": w[2].strftime("%H:%M") if w[2] else None}
                if (w := self.window_now()) else None,
                "held": self.held(), "night": self.was_night,
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
            self._leave_out(full, "unfit")  # never drawn, and not offered again
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
            w = self._window(want, self.now().date())
            return "%s%s" % ("the morning picture" if want == "morning" else "tonight's show",
                             ", %s–%s" % (w[0].strftime("%H:%M"), w[1].strftime("%H:%M")) if w else "")
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
            wait = self.change_at() - time.time()  # the interval can change on the page
            want = self.wanted()
            if want == "music" and time.time() < self.retry_at:
                await self._nap(self.retry_at - time.time())  # a new song doesn't try a sleeping TV again sooner
                continue
            if want == "music" and self.state.d.get("music_shown") == self.music["key"]:
                await self._nap(60)  # the same song still
                continue
            if want == "music" and self.seen["power"] is False:
                await self._nap(60)  # the TV is off: the song goes up when it comes on, not into a sleeping TV
                continue
            if want != "music" and (self.state.d.get("music_shown") or self.state.d.get("before")):
                why, job = "the music stopped", self._after_music(want)
            elif want == "rotation" and self.cfg.get("paused"):
                await self._nap(60)  # resumed on the page or from Home Assistant
                continue
            elif want == "fixed" or (want in MADE and not self.due()) or (want in ("rotation", "saver") and wait > 0):
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
                # Art Mode only just after the schedule turned the TV on: never over something else
                # (and not once it's been seen out of Art Mode, after the first couple of minutes)
                since = time.time() - self.woke_at
                woke = want in MADE and since < WOKE_MINUTES * 60 and (since < 120 or self.seen["art_mode"] is not False)
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
