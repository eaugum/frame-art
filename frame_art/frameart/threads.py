"""Threads for blocking calls. The schedule and the power look have a few of their own, so nothing else (a slow TV
tab, Stasera, Home Assistant, a source) can take them all; the sources have theirs; everything else uses asyncio's."""
import asyncio
import concurrent.futures
import contextvars
import functools

SCHEDULE = concurrent.futures.ThreadPoolExecutor(4, "schedule")
FETCHERS = concurrent.futures.ThreadPoolExecutor(8, "sources")  # listing, pictures and thumbnails
_pool = contextvars.ContextVar("pool", default=None)


def schedule():
    """From here on, the calling task's blocking calls (and those of the tasks it starts) use the schedule's threads."""
    _pool.set(SCHEDULE)


async def run_in(pool, f, *args, **kw):
    """f(*args, **kw) in one of pool's threads (None: asyncio's), like asyncio.to_thread: the context goes along (the
    event log's why)."""
    call = functools.partial(contextvars.copy_context().run, f, *args, **kw)
    return await asyncio.get_running_loop().run_in_executor(pool, call)


async def run(f, *args, **kw):
    """f(*args, **kw) in a thread: the schedule's in the schedule, else asyncio's."""
    return await run_in(_pool.get(), f, *args, **kw)
