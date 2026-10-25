"""The rotation: every interval a random picture from a random source that's on, up to the TV, shown, and our older
uploads removed. It remembers in state.json what it uploaded (only those are ever deleted), what it showed lately
and when, so a restart of the Pi or the TV picks up where it was.
"""
import asyncio
import json
import logging
import os
import random
import time

from . import __version__, image, sources
from .tv import TV

log = logging.getLogger(__name__)

RECENT = 200  # not the same picture again within this many changes (or the whole pool, if it's smaller)
RETRY_MINUTES = 5  # TV off or away


class State:
    def __init__(self, path):
        self.path = path
        try:
            with open(path) as f:
                self.d = json.load(f)
        except (OSError, ValueError):
            self.d = {}
        for k, v in (("uploaded", []), ("recent", []), ("bad", []), ("pools", {}), ("changed", 0)):
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
        self.cfg = cfg
        self.data = data_dir
        self.state = State(os.path.join(data_dir, "state.json"))
        self.sources = sources.from_config(cfg)
        self.next_path = os.path.join(data_dir, "next.jpg")
        self.showing_path = os.path.join(data_dir, "showing.jpg")
        self.lock = asyncio.Lock()  # one conversation with the TV at a time: the timer, Home Assistant, Frame TV

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
        bad, recent = set(self.state["bad"]), self.state["recent"]
        for _ in range(12):
            choices = [(s, self.pool(s)) for s in self.sources]
            choices = [(s, [k for k in keys if s.name + ":" + k not in bad]) for s, keys in choices]
            choices = [(s, keys) for s, keys in choices if keys]
            if not choices:
                return None
            src, keys = random.choice(choices)
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

    def prepared(self):
        """The picture for the next change, made once and kept until it's on the TV (the TV may be off for hours)."""
        meta = self.state.d.get("next")
        if meta and os.path.exists(self.next_path):
            with open(self.next_path, "rb") as f:
                return f.read(), meta["label"], meta["key"]
        got = self.pick()
        if got:
            with open(self.next_path, "wb") as f:
                f.write(got[0])
            self.state["next"] = {"label": got[1], "key": got[2]}
            self.state.save()
        return got

    # MARK: - The TV

    async def change(self, art_mode=False):
        """A new picture. With art_mode, the TV goes to Art Mode too (Home Assistant, Frame TV); the timer never does."""
        async with self.lock:
            return await self._change(art_mode)

    async def _change(self, force):
        got = self.prepared()
        if not got:
            log.warning("nothing to show: no source is on, or none has pictures")
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
        return {"version": __version__, "showing": self.state.d.get("showing"), "changed": int(self.state["changed"]),
                "next": int(self.state["changed"] + interval) if self.state["changed"] else None,
                "interval_minutes": interval / 60, "sources": [s.name for s in self.sources], "busy": self.lock.locked()}

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
        interval = self.interval()
        log.info("Frame Art %s for %s, every %g min, sources: %s", __version__, self.cfg["tv_host"], interval / 60,
                 ", ".join(s.name for s in self.sources) or "none")
        while True:
            wait = self.state["changed"] + interval - time.time()
            if wait > 0:
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
