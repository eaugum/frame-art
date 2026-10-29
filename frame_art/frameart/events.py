"""What happened, when and why (AUG-1520): the add-on's own log of what it did and what it saw the TV do, for the
Debug tab on its page and GET /events.

An event is {id, at, source, kind, detail, why}. id is the time in milliseconds, made unique, so it orders the events and
?since= can ask for those after one. why says what set it off: the caller sets it with because(), and every event
inside, also in the threads and tasks it starts, gets it (a context variable). The last days are kept in
events.jsonl in the data folder, written a line at a time and trimmed once a day; the newest are in memory too.

What the TV does by itself is told apart from what we made it do (AUG-1523): before a command, expect() says what
should follow ("art_mode_on"), and cause() gives the why of a change that was expected, or None: from outside.
"""
import collections
import contextlib
import contextvars
import json
import logging
import os
import threading
import time

log = logging.getLogger(__name__)

KEEP_DAYS = 7
MEMORY = 5000  # the newest events, answered without reading the file
LIMIT = 2000  # at most this many in one answer
EXPECT_SECONDS = 120  # a change this soon after our command is ours

_why = contextvars.ContextVar("why", default="")
_lock = threading.Lock()
_recent = collections.deque(maxlen=MEMORY)
_path = None
_last_id = 0
_trimmed = 0
_expected = []  # [until, what, why]


def setup(data_dir):
    """Reads what's kept from before a restart, and trims it."""
    global _path
    _path = os.path.join(data_dir, "events.jsonl")
    with _lock:
        _trim()


def _read():
    try:
        with open(_path, encoding="utf-8") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except ValueError:
                    pass  # a line cut short by a restart
    except OSError:
        return


def _trim():
    """Drops what's older than KEEP_DAYS from the file, and fills the memory from what's left. Under _lock."""
    global _last_id, _trimmed
    _trimmed = time.time()
    cutoff = (_trimmed - KEEP_DAYS * 86400) * 1000
    kept = [e for e in _read() if e.get("id", 0) >= cutoff]
    _recent.clear()
    _recent.extend(kept)
    _last_id = max([_last_id] + [e["id"] for e in kept])
    if not _path:
        return
    try:
        tmp = _path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(e, ensure_ascii=False) + "\n" for e in kept)
        os.replace(tmp, _path)
    except OSError as e:
        log.warning("couldn't trim the event log (%s)", e)


def add(source, kind, detail="", why=None, at=None):
    """One event. source: tv, rotation, morning, tonight, music, saver, mqtt, api or app; kind a short word for what
    happened; detail what, in words; why defaults to what because() said. at: when it happened, when that was earlier
    than now (Frame TV's queued events); the id is still now, so ?since= sees it."""
    global _last_id
    now = time.time()
    why = _why.get() if why is None else why
    with _lock:
        _last_id = max(int(now * 1000), _last_id + 1)
        e = {"id": _last_id, "at": at or _last_id / 1000, "source": source, "kind": kind, "detail": str(detail or ""),
             "why": why}
        _recent.append(e)
        if not _path:
            return e
        if now - _trimmed > 86400:
            _trim()
        try:
            with open(_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        except OSError as err:
            log.warning("couldn't write the event log (%s)", err)
    return e


@contextlib.contextmanager
def because(why):
    """Events inside are because of this ("the add-on's page: next", "Morgenbildet at 07:00")."""
    token = _why.set(why)
    try:
        yield
    finally:
        _why.reset(token)


def why():
    return _why.get()


def expect(what, seconds=EXPECT_SECONDS):
    """We're about to make the TV do `what` (power_on, art_mode_on, art_mode_off), because of why()."""
    now = time.time()
    with _lock:
        _expected[:] = [x for x in _expected if x[0] > now] + [[now + seconds, what, _why.get() or "Frame Art"]]


def cause(what):
    """The why of the command that should have done `what` (used up), or None: it came from outside."""
    now = time.time()
    with _lock:
        for x in _expected:
            if x[1] == what and x[0] > now:
                _expected.remove(x)
                return x[2]
    return None


def since(after=0, until=None, limit=LIMIT):
    """The events with an id after `after` (and before `until`), oldest first; the newest `limit` of them, and whether
    there were more."""
    with _lock:
        if _recent and after >= _recent[0]["id"] - 1:
            got = [e for e in _recent if e["id"] > after]
        else:
            got = [e for e in _read() if e.get("id", 0) > after]
    if until:
        got = [e for e in got if e["id"] < until]
    return got[-limit:], len(got) > limit
