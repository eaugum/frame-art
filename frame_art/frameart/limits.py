"""Limits for a piece of picture work (a job) in a thread: a deadline for all it asks of the network (within), and
the memory it holds, raw downloads and decoded pictures together. A job may hold SMALL on its own, of it RAW_SMALL in
downloads; past that it needs the one big slot, so only one job at a time holds more, and never more than MEMORY. When a job ends, whatever happens,
its pictures are closed and the slot is given back: nothing waits for the garbage collector."""
import contextlib
import contextvars
import functools
import threading
import time


MEMORY = 420 * 2 ** 20  # one job at most: a 90 MP picture is 360 MB decoded, and its file comes on top
SMALL = 64 * 2 ** 20  # any job without the big slot: a 4K PNG's thumbnail (33 MB decoded and its file), a listing's page
RAW_SMALL = 32 * 2 ** 20  # of SMALL, downloads and files: eight 85 MB downloads at once can't add up
WAIT = 60  # seconds a job waits for the big slot, then Busy

_until = contextvars.ContextVar("until", default=None)  # within()'s deadline
_big = threading.Lock()
_local = threading.local()


class Busy(Exception):
    """Another big picture is being made: this one is tried again later, it isn't unfit."""


class TooBig(Exception):
    """More memory than a job may have: skipped for now, not unfit (it's our limit, not a bad picture)."""


def within(seconds, f, *args):
    """f(*args), with all it asks of the network and its waits (Retry-After, the big slot) done within seconds."""
    token = _until.set(time.monotonic() + seconds)
    try:
        return f(*args)
    finally:
        _until.reset(token)


def left():
    """Seconds left of within()'s time, or None outside it."""
    until = _until.get()
    return None if until is None else until - time.monotonic()


@contextlib.contextmanager
def job():
    jobs = _local.__dict__.setdefault("jobs", [])
    mine = {"held": 0, "raw": 0, "big": False, "pictures": []}
    jobs.append(mine)
    try:
        yield
    finally:
        jobs.pop()
        for img in mine["pictures"]:
            img.close()  # its pixels go now, even if something still refers to it
        if mine["big"]:
            _big.release()


def in_job(f):
    """f, each call a job of its own."""
    @functools.wraps(f)
    def run(*args, **kw):
        with job():
            return f(*args, **kw)
    return run


def hold(n, raw=False):
    """n more bytes for this thread's job (raw: downloaded or read): past SMALL or RAW_SMALL it waits for the big slot;
    past MEMORY it's refused. Nothing outside a job."""
    jobs = getattr(_local, "jobs", None)
    if not jobs:
        return
    total = sum(j["held"] for j in jobs) + n
    if total > MEMORY:
        raise TooBig("%d MB for one picture is more than %d MB" % (total >> 20, MEMORY >> 20))
    raws = sum(j["raw"] for j in jobs) + (n if raw else 0)
    if (total > SMALL or raws > RAW_SMALL) and not any(j["big"] for j in jobs):
        wait = WAIT if left() is None else max(0, min(WAIT, left()))
        if not _big.acquire(timeout=wait):
            raise Busy("another big picture is being made")
        jobs[-1]["big"] = True
    jobs[-1]["held"] += n
    jobs[-1]["raw"] += n if raw else 0


def let_go(n):
    """n downloaded bytes this thread's job no longer holds; back under SMALL, it gives the big slot back."""
    jobs = getattr(_local, "jobs", None)
    if not jobs:
        return
    jobs[-1]["held"] = max(0, jobs[-1]["held"] - n)
    jobs[-1]["raw"] = max(0, jobs[-1]["raw"] - n)
    if sum(j["held"] for j in jobs) <= SMALL and sum(j["raw"] for j in jobs) <= RAW_SMALL:
        for j in jobs:
            if j["big"]:
                j["big"] = False
                _big.release()


def keep(img):
    """img is closed when this thread's job ends."""
    jobs = getattr(_local, "jobs", None)
    if jobs:
        jobs[-1]["pictures"].append(img)
