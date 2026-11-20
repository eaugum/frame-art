"""The Frame's Art Mode, through samsungtvws. One connection per change: the TV sleeps, wakes and restarts between.
Besides, watch() keeps one open to hear when Art Mode goes off, and launch() opens an app (AUG-1494)."""
import asyncio
import json
import logging
import re
import urllib.error
import urllib.request

from samsungtvws.async_art import SamsungTVAsyncArt
from samsungtvws.async_remote import SamsungTVWSAsyncRemote
from samsungtvws.exceptions import ConnectionFailure
from samsungtvws.remote import SendRemoteKey

from . import events

log = logging.getLogger(__name__)

MY_PHOTOS = "MY-C0002"

# The TV's Art Mode settings the TV tab can change (AUG-1722): name -> samsungtvws' call. The values are strings.
ART_SETTINGS = {"brightness": "set_brightness", "color_temperature": "set_color_temperature",
                "motion_sensitivity": "set_motion_sensitivity", "motion_timer": "set_motion_timer",
                "brightness_sensor_setting": "set_brightness_sensor_setting"}

# Apps the TV tab asks about (AUG-1722): the streaming apps in Frame TV's library, by the ids the TV's REST API knows
# (Tizen ids, and Netflix's, Prime Video's and Apple TV's older Smart Hub ids). Those not installed answer 404.
APPS = ("3201907018807", "3201910019365", "3201807016597", "9Ur5IzDKqV.TizenYouTube", "n8N84lD1cR.NRKTVBeta",
        "PyZfkXAf88.tv2sumoTizen", "niYSnzL6h1.Viaplay", "5b8c3eb16b.BeamCTVDev", "NvZ26VG9Yw.HBOGOLAG",
        "MCmYXNxgcu.DisneyPlus", "rJeHak5zRg.Spotify", "5SLwh7m3En.TizenYouTubeKids", "AprZAARz4r.Jellyfin",
        "vIutycUzou.SteamLink")


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
        events.expect("art_mode_on")
        await asyncio.wait_for(self.art.set_artmode("on"), 30)
        if await self._settled():
            return  # the event log has it from the art channel
        log.info("set_artmode didn't take; pressing power once")
        events.add("tv", "power_key", "set_artmode didn't take; pressing power once")
        await self._keys([SendRemoteKey.click("KEY_POWER")])
        if not await self._settled():
            events.add("tv", "art_mode_failed", "the TV didn't go to Art Mode, even after power")
            raise RuntimeError("the TV didn't go to Art Mode")
        events.add("tv", "art_mode_on", "Art Mode on, after pressing power")

    async def _keys(self, commands):
        """Keys on the remote control channel, which shares the art channel's token."""
        remote = SamsungTVWSAsyncRemote(host=self.host, port=8002, token_file=self.token_file, name=self.name,
                                        timeout=30)
        try:
            await asyncio.wait_for(remote.start_listening(), 40)
            await remote.send_commands(commands)
        finally:
            try:
                await remote.close()
            except Exception:
                pass

    async def power_off(self):
        """The TV to standby: power held for 3 s, as Home Assistant does for The Frame (a short press only goes
        between Art Mode and TV). From Art Mode, or from anything when nobody's home."""
        events.expect("power_off")
        await self._keys(SendRemoteKey.hold("KEY_POWER", 3))

    async def motion_timer(self):
        """The TV's own Art Mode timer ("Sleep After"): (value, valid values), e.g. ("60", ["off", "5", ...])."""
        got = await self._ask(lambda: self.art.get_artmode_settings("motion_timer"), tries=2)
        valid = got.get("valid_values") or []
        if isinstance(valid, str):
            try:
                valid = json.loads(valid)
            except ValueError:
                valid = [valid]
        return str(got.get("value")), [str(v) for v in valid]

    async def set_motion_timer(self, value):
        await asyncio.wait_for(self.art.set_motion_timer(value), 30)

    async def light_sensor(self):
        """The TV's light sensor in Art Mode ("on"/"off"), which puts it in standby in a dark room; None on a TV
        without one."""
        got = await self._ask(lambda: self.art.get_artmode_settings("brightness_sensor_setting"), tries=2)
        return str(got.get("value")) if isinstance(got, dict) and got.get("value") is not None else None

    async def set_light_sensor(self, value):
        await asyncio.wait_for(self.art.set_brightness_sensor_setting(value), 30)

    async def info(self):
        """What the art channel says about Art Mode, for the TV tab (AUG-1722); each part on its own, since an older
        TV can lack one. Only reads."""
        out = {}
        for name, call in (("api_version", self.art.get_api_version), ("device", self.art.get_device_info),
                           ("settings", self.art_settings), ("slideshow", self.art.get_slideshow_status),
                           ("current", self.art.get_current)):
            try:
                out[name] = await self._ask(call, wait=15, tries=2)
            except Exception as e:
                log.info("the art channel's %s: %s: %s", name, type(e).__name__, e)
                out[name] = None
        try:
            out["my_photos"] = sorted(await self.my_photos())
        except Exception as e:
            log.info("the art channel's My Photos: %s: %s", type(e).__name__, e)
            out["my_photos"] = None
        return out

    async def art_settings(self):
        """The Art Mode settings as the TV has them: [{item, value, min, max} or {item, value, valid_values}]."""
        got = await self.art.get_artmode_settings()
        for x in got if isinstance(got, list) else ():
            if isinstance(x.get("valid_values"), str):  # motion_timer's comes as JSON in a string
                try:
                    x["valid_values"] = json.loads(x["valid_values"])
                except ValueError:
                    pass
        return got

    async def set_art_setting(self, name, value):
        """One of ART_SETTINGS; then the settings as the TV has them after. The TV may not answer a set_ request in
        time (samsungtvws asserts), so what counts is what it says after."""
        try:
            await asyncio.wait_for(getattr(self.art, ART_SETTINGS[name])(str(value)), 30)
        except AssertionError:
            log.info("no answer to %s=%s; reading it back", name, value)
        await asyncio.sleep(1)
        return await self._ask(self.art_settings, wait=15, tries=2)

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
    for each of the art app's events (art_mode_changed, go_to_standby...), and channel_closed when it stops
    answering. Only listens: it sends nothing but the library's own question about Art Mode when it connects."""
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
        listening = False
        try:
            await asyncio.wait_for(art.start_listening(), 60)
            listening = True
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
        if listening:
            await on_event("channel_closed", {})
        await asyncio.sleep(60)


def _rest(host, method, path, timeout=10):
    req = urllib.request.Request("http://%s:8001/api/v2/%s" % (host, path), method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def device(host, timeout=10):
    """What the TV says about itself on port 8001 (no token): its name, model, network, PowerState... Raises when it
    doesn't answer."""
    return _rest(host, "GET", "", timeout)


_SOAP = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
         's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:{0} '
         'xmlns:u="urn:schemas-upnp-org:service:RenderingControl:1"><InstanceID>0</InstanceID><Channel>Master</Channel>'
         '</u:{0}></s:Body></s:Envelope>')


def _upnp(host, action, answer, timeout):
    req = urllib.request.Request("http://%s:9197/upnp/control/RenderingControl1" % host,
                                 data=_SOAP.format(action).encode(), method="POST",
                                 headers={"Content-Type": 'text/xml; charset="utf-8"',
                                          "SOAPACTION": '"urn:schemas-upnp-org:service:RenderingControl:1#%s"' % action})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        got = re.search(r"<%s>([^<]*)</%s>" % (answer, answer), r.read().decode("utf-8", "replace"))
    if not got:
        raise ValueError("no %s in the answer to %s" % (answer, action))
    return got.group(1)


def volume(host, timeout=3):
    """{volume: 0-100, muted} from the TV's media renderer (UPnP, port 9197, no token; AUG-1728). Raises when it
    doesn't answer."""
    return {"volume": int(_upnp(host, "GetVolume", "CurrentVolume", timeout)),
            "muted": _upnp(host, "GetMute", "CurrentMute", timeout) in ("1", "true")}


def app_state(host, app_id, timeout=5):
    """{id, name, running, visible, version} for an installed app, None when it isn't installed."""
    try:
        return _rest(host, "GET", "applications/" + app_id, timeout)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def powered_on(host, timeout=10):
    """True when the TV says it's on (not in standby); False when it doesn't answer."""
    try:
        return (_rest(host, "GET", "", timeout).get("device") or {}).get("PowerState") == "on"
    except Exception:
        return False


def launch(host, app_id):
    """Opens an app on the TV, or brings it forward when it's running: the REST API on port 8001, with no token. The
    websocket's ed.apps.launch doesn't do it from Art Mode's menu; this does (tested 26.10.2026)."""
    events.expect("art_mode_off")  # an app in front ends Art Mode, when it was on
    return _rest(host, "POST", "applications/" + app_id, timeout=15) is True
