"""The Frame's Art Mode, through samsungtvws. One connection per change: the TV sleeps, wakes and restarts between.
Besides, watch() keeps one open to hear when Art Mode goes off, and launch() opens an app (AUG-1494)."""
import asyncio
import json
import logging
import urllib.request

from samsungtvws.async_art import SamsungTVAsyncArt
from samsungtvws.async_remote import SamsungTVWSAsyncRemote
from samsungtvws.exceptions import ConnectionFailure
from samsungtvws.remote import SendRemoteKey

from . import events

log = logging.getLogger(__name__)

MY_PHOTOS = "MY-C0002"


async def _art(**kw):
    """SamsungTVAsyncArt asks the TV for its model with a blocking HTTP request when it's made, which waits for the
    whole timeout when the TV sleeps; in a thread, so the rest (MQTT's keepalive) goes on meanwhile."""
    return await asyncio.to_thread(SamsungTVAsyncArt, **kw)


class TV:
    def __init__(self, host, token_file, name="FrameArt"):
        self.host, self.token_file, self.name = host, token_file, name

    async def _new(self):
        # timeout covers the first connection, while someone answers "Allow" on the TV
        return await _art(host=self.host, port=8002, token_file=self.token_file, name=self.name, timeout=60)

    async def pair(self):
        """The art channel never asks "Allow"; it stays silent without a token. The remote control channel asks, and
        its token works for both. No keys are sent."""
        log.info("no token yet: answer 'Allow' for %s on the TV", self.name)
        remote = SamsungTVWSAsyncRemote(host=self.host, port=8002, token_file=self.token_file, name=self.name,
                                        timeout=60)
        try:
            await asyncio.wait_for(remote.start_listening(), 90)
        finally:
            try:
                await remote.close()
            except Exception:
                pass
        if not self.has_token():
            raise RuntimeError("the TV gave no token (was 'Allow' answered?)")
        log.info("got a token from the TV")

    def has_token(self):
        try:
            with open(self.token_file) as f:
                return bool(f.read().strip())
        except OSError:
            return False

    async def __aenter__(self):
        if not self.has_token():
            await self.pair()
        for attempt in range(4):
            self.art = await self._new()
            try:
                await asyncio.wait_for(self.art.start_listening(), 90)
                return self
            except ConnectionFailure as e:
                # samsungtvws gives up when another client (HA, a phone) connects or leaves at the same moment
                if "ms.channel.client" not in str(e) or attempt == 3:
                    raise
                log.info("another client on the TV at the same moment; connecting again")
                await asyncio.sleep(5)

    async def __aexit__(self, *exc):
        try:
            await self.art.close()
        except Exception:
            pass

    async def _ask(self, call, wait=30, tries=4):
        """samsungtvws waits 2 s for most answers and asserts when none came; the art app, just started (Art Mode
        switched on), can take longer. call() makes a new request each time."""
        for attempt in range(tries):
            try:
                return await asyncio.wait_for(call(), wait)
            except (AssertionError, asyncio.TimeoutError):
                if attempt == tries - 1:
                    raise RuntimeError("the art app on the TV didn't answer")
                await asyncio.sleep(3)

    async def in_art_mode(self):
        return await self._ask(self.art.get_artmode) == "on"

    async def art_mode_on(self):
        """Only called when the TV has just said it's on and not in Art Mode, so a short press on power (the
        fallback) can only go from TV to Art Mode, never switch it off."""
        await asyncio.wait_for(self.art.set_artmode("on"), 30)
        if await self._settled():
            events.add("tv", "art_mode_on", "Art Mode on")
            return
        log.info("set_artmode didn't take; pressing power once")
        events.add("tv", "power_key", "set_artmode didn't take; pressing power once")
        remote = SamsungTVWSAsyncRemote(host=self.host, port=8002, token_file=self.token_file, name=self.name,
                                        timeout=30)
        try:
            await asyncio.wait_for(remote.start_listening(), 40)
            await remote.send_command(SendRemoteKey.click("KEY_POWER"))
        finally:
            try:
                await remote.close()
            except Exception:
                pass
        if not await self._settled():
            events.add("tv", "art_mode_failed", "the TV didn't go to Art Mode, even after power")
            raise RuntimeError("the TV didn't go to Art Mode")
        events.add("tv", "art_mode_on", "Art Mode on, after pressing power")

    async def _settled(self):
        for _ in range(5):
            await asyncio.sleep(2)
            try:
                if await self.in_art_mode():
                    return True
            except Exception:
                pass
        return False

    async def slideshow_on(self):
        try:
            s = await self._ask(self.art.get_slideshow_status, tries=2)
            return s.get("value") not in (None, "off")
        except Exception:
            return False

    async def upload(self, jpeg):
        # a missing answer to send_image comes before any bytes are sent, so asking again is safe
        return await self._ask(lambda: self.art.upload(jpeg, file_type="JPEG", matte="none", portrait_matte="none",
                                                       timeout=120), wait=180, tries=3)

    async def show(self, content_id, now):
        """Makes it the picture in Art Mode; with now=False it's ready for the next time Art Mode comes on, and
        whatever is on the screen stays."""
        await asyncio.wait_for(self.art.select_image(content_id, category=MY_PHOTOS, show=now), 30)

    async def my_photos(self):
        return {a["content_id"] for a in await self._ask(lambda: self.art.available(MY_PHOTOS, timeout=20), wait=40)}

    async def delete(self, content_ids):
        if content_ids:
            await asyncio.wait_for(self.art.delete_list(list(content_ids)), 60)


# MARK: - Leaving Art Mode (AUG-1494)

async def watch(host, token_file, on_event, name="FrameArtWatch"):
    """Listens on the art channel for good, connecting again when the TV has been away; on_event(sub_event, data)
    for each of the art app's events (art_mode_changed, go_to_standby...). Only listens: it sends nothing but the
    library's own question about Art Mode when it connects."""
    while True:
        try:
            art = await _art(host=host, port=8002, token_file=token_file, name=name, timeout=30)
        except Exception as e:
            log.debug("art channel not answering (%s: %s)", type(e).__name__, e)
            await asyncio.sleep(60)
            continue
        seen = art.process_event

        async def heard(event=None, response=None):
            try:
                if event == "d2d_service_message":
                    data = json.loads(response["data"])
                    await on_event(data.get("event"), data)
            except Exception as e:
                log.warning("watching Art Mode: %s: %s", type(e).__name__, e)
            await seen(event, response)

        art.process_event = heard
        try:
            await asyncio.wait_for(art.start_listening(), 60)
            log.info("listening for Art Mode going off")
            events.add("tv", "channel_open", "the art channel answers: listening for Art Mode", why="")
            while art.is_alive():
                await asyncio.sleep(10)
            log.info("the TV closed the art channel; connecting again in a minute")
            events.add("tv", "channel_closed", "the TV closed the art channel (off, or asleep)", why="")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.debug("art channel not answering (%s: %s)", type(e).__name__, e)  # off or away: tried each minute
        finally:
            try:
                await art.close()
            except Exception:
                pass
        await asyncio.sleep(60)


def _rest(host, method, path, timeout=10):
    req = urllib.request.Request("http://%s:8001/api/v2/%s" % (host, path), method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def powered_on(host, timeout=10):
    """True when the TV says it's on (not in standby); False when it doesn't answer."""
    try:
        return (_rest(host, "GET", "", timeout).get("device") or {}).get("PowerState") == "on"
    except Exception:
        return False


def launch(host, app_id):
    """Opens an app on the TV, or brings it forward when it's running: the REST API on port 8001, with no token. The
    websocket's ed.apps.launch doesn't do it from Art Mode's menu; this does (tested 26.10.2026)."""
    return _rest(host, "POST", "applications/" + app_id, timeout=15) is True
