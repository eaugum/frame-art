"""A small HTTP API on the home network, for Home Assistant (rest_command) and Frame TV on the TV.

GET  /         a page with what's showing, the buttons, the sources to tick, the settings and Stasera (the
               add-on's page in Home Assistant, through ingress)
GET  /status   what's showing, when it changed and when it changes next, the mode, the categories, how many pictures
               each source has (null: not read yet; reading says some are being read), how many each source
               and category has hidden, seen and found unfit (left_out), the settings and Stasera
GET  /showing.jpg  the picture
GET  /category?name=Japan  for choosing a picture: what's been on the wall lately and 24 at random, from the
               category's sources that are ticked
GET  /thumb?picture=…  a small copy of a picture (a key from /category)
GET  /tv       whether the TV is off ({"off": true}), asked of the TV; null while Home Assistant doesn't answer
POST /tv/on    the TV on with Wake-on-LAN through Home Assistant, then back_app opened, without waiting for the TV's
               turn
POST /next     a new picture now; ?art_mode=1 puts the TV in Art Mode too; ?what=morning or ?what=tonight shows
               Morgenbildet or tonight's show instead of one from the rotation. Ends a fixed picture. ?wake=1 (and on
               /show) turns the TV on first (Wake-on-LAN) when it's off.
POST /show?picture=…  that picture now, in Art Mode, standing until the next morning picture (a fixed picture)
POST /artmode  Art Mode on, with the picture it has
POST /never    what's on the wall (from a source; showing_key in /status) is never drawn again, and another comes;
               ?picture=… is that picture instead (a key from /category), and the wall only changes if it's on it
POST /settings JSON with what to change: sources_off (the sources not ticked), interval_minutes, keep,
               morning, morning_days, morning_tv_on, tonight, tonight_days, tonight_tv_on (a week: seven
               {on, from, until}, Monday first), night_timer_minutes, away_off, tv_timer_off, screensaver,
               screensaver_stasera, music, music_home_only (the music); mode shuffle ends a fixed picture, and mode category with category ticks only that
               category's sources. New sources_off ends a fixed picture too. /schedule is the same.
POST /stasera/link    a code to approve in Stasera (in /status under pairing until it's approved)
POST /stasera/unlink  forgets the Stasera token

POST /saver    Frame TV's screensaver started: Art Mode on, with what we watch in Stasera when screensaver_stasera is
               on, until Art Mode goes off (AUG-1494); ?minutes=5 changes the picture that often meanwhile

POST /event    what Frame TV did, for the event log (AUG-1523): {"events": [{"at": ms, "kind": "hidden", "detail": "…"}]}
GET  /events?since=<id>  what happened, when and why (AUG-1520), oldest first: {"events": [...], "more": bool}, the
               newest 2000 after that id (an id is the time in ms); ?until=<id> for those before one
GET  /events/export  all of it (the last 7 days), as a file

Every call from outside needs the add-on's key (AUG-1496), as "Authorization: Bearer <key>" or ?key=<key>: it's
api_key in the add-on's options (a new one made and written there when it's empty). The page itself, through ingress,
doesn't need it. /show and /thumb took the picture as ?key= before AUG-1777; that still works when the key comes in the
header. The answers wait for the TV (up to a minute or two).
"""
import asyncio
import collections
import hmac
import json
import logging
import os
import re
import secrets
import time
import urllib.request

from aiohttp import web

from . import events, i18n, limits, redact, sources, threads

log = logging.getLogger(__name__)

with open(os.path.join(os.path.dirname(__file__), "page.html"), encoding="utf-8") as f:
    PAGE = f.read()  # the add-on's page

CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization"}
APP_EVENTS = 100  # at most this many from Frame TV in one call
INGRESS = "172.30.32.2"  # the Supervisor, when the page is opened in Home Assistant


def api_key(cfg, data_dir):
    """The key Frame TV and others send: api_key in the options. Without one, a new key, written into the add-on's
    options so it can be read there. api_key.txt keeps a key made here only until the options have it (AUG-1777), so
    an emptied option makes a new key instead of bringing an old one back."""
    path = os.path.join(data_dir, "api_key.txt")
    if (cfg.get("api_key") or "").strip():
        _forget(path)
        return cfg["api_key"].strip()
    key = _stored(path)
    if not key:
        key = secrets.token_urlsafe(24)
        log.info("made a new key for the API")
        try:
            with open(path, "w") as f:
                f.write(key)
            os.chmod(path, 0o600)
        except OSError as e:
            log.warning("couldn't keep the API's key in %s (%s)", path, type(e).__name__)
    if _into_options(data_dir, key, path if _stored(path) == key else None):
        _forget(path)
    return key


def _stored(path):
    """A key made here that the options didn't get (or an older version's); "" when there's none, or it's damaged."""
    try:
        with open(path) as f:
            key = f.read().strip()
    except (OSError, ValueError):
        return ""
    return key if re.fullmatch(r"[A-Za-z0-9_-]{16,}", key) else ""


def _forget(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("couldn't remove %s (%s)", path, type(e).__name__)


def _into_options(data_dir, key, kept):
    """api_key into the add-on's own options, through the Supervisor (hassio_api). True when it took it. kept: the
    file the key is in meanwhile, or None."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return False
    try:
        with open(os.path.join(data_dir, "options.json")) as f:
            options = json.load(f)
        req = urllib.request.Request("http://supervisor/addons/self/options", method="POST",
                                     data=json.dumps({"options": dict(options, api_key=key)}).encode(),
                                     headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10):
            pass
        log.info("the API's key is now in the add-on's options (api_key)")
        return True
    except Exception as e:
        log.warning("couldn't write the API's key into the options (%s: %s); %s", type(e).__name__, e,
                    "it's kept in %s until then" % kept if kept else "it couldn't be kept either, so a new one at the "
                    "next start")
        return False


def app(rotation):
    key = api_key(rotation.cfg, rotation.data)
    redact.hide(key)
    events.scrub()

    def ingress(request):
        return request.remote == INGRESS

    def picture_of(request):
        """The picture a call is about: ?picture=, or ?key= from callers before AUG-1777 when the API's key came
        another way (the header, or ingress)."""
        got = request.query.get("picture")
        if got is None and (ingress(request) or request.headers.get("Authorization", "").startswith("Bearer ")):
            got = request.query.get("key")
        return not_the_key(got or "")

    def not_the_key(picture):
        """A picture that holds the API's key is refused, before it goes into the log and the events."""
        if redact.holds(picture):
            raise web.HTTPBadRequest(text=json.dumps({"ok": False, "error": "send the picture as ?picture="}),
                                     content_type="application/json", headers=CORS)
        return picture

    def caller(request):
        """Who asked, for the event log's why."""
        if ingress(request):
            return "the add-on's page"
        if request.remote == rotation.cfg.get("tv_host"):
            return "Frame TV"
        if request.headers.get("User-Agent", "").startswith("HomeAssistant"):
            return "Home Assistant"
        return request.remote or "someone"

    @web.middleware
    async def keyed(request, handler):
        if request.method == "OPTIONS" or (request.method == "GET" and request.path == "/"):
            return await handler(request)
        given = request.headers.get("Authorization", "")
        given = given[7:] if given.startswith("Bearer ") else request.query.get("key", "")
        if not ingress(request) and not hmac.compare_digest(given.encode(), key.encode()):
            return web.json_response({"ok": False, "error": "wrong or no key (api_key in the add-on's options)"}, status=401,
                                     headers=CORS)
        if request.method != "POST":
            return await handler(request)
        with events.because("%s (%s)" % (caller(request), request.path)):
            return await handler(request)

    async def status(request):
        return web.json_response(rotation.status(), headers=CORS)

    async def act(request, what):
        try:
            ok = await what()
            return web.json_response(dict(rotation.status(), ok=bool(ok)), headers=CORS)
        except Exception as e:
            log.info("%s failed (%s: %s)", request.path, type(e).__name__, e)
            return web.json_response(dict(rotation.status(), ok=False, error=str(e) or type(e).__name__),
                                     status=503, headers=CORS)

    async def next_(request):
        art_mode = request.query.get("art_mode", "") in ("1", "true", "yes")
        what = request.query.get("what") or None
        if what not in (None, "morning", "tonight"):
            return web.json_response({"ok": False, "error": "what is morning or tonight"}, status=400, headers=CORS)
        log.info("asked for %s%s", what or "a new picture", " in Art Mode" if art_mode else "")
        events.add("api", "next", "%s%s" % (what or "a new picture", " in Art Mode" if art_mode else ""))

        async def go():
            await wake(request)
            return await rotation.change(art_mode=art_mode, what=what, join=not what)
        return await act(request, go)

    async def wake(request):
        """?wake=1: the TV on first, when it's off (the page asked)."""
        if request.query.get("wake") == "1" and await rotation.tv_off():
            await rotation.turn_on()

    async def tv_on(request):
        log.info("asked to turn the TV on")
        events.add("api", "tv_on", "turn the TV on")
        return await act(request, rotation.wake_up)

    async def tv_off(request):
        log.info("asked to turn the TV off")
        events.add("api", "tv_off", "turn the TV off")
        return await act(request, rotation.power_off)

    async def tv(request):
        return web.json_response({"off": await rotation.tv_off()}, headers=CORS)

    async def tv_info(request):
        """The TV tab (AUG-1722): ?fresh=1 asks the TV first; without, the last answers."""
        return web.json_response(await rotation.tv_info(request.query.get("fresh") == "1"), headers=CORS)

    async def tv_report(request):
        """Frame TV's report on the TV (AUG-1722), sent when it starts."""
        try:
            rotation.tv_report(await request.json())
        except ValueError as e:
            return web.json_response({"ok": False, "error": str(e) or "send JSON"}, status=400, headers=CORS)
        return web.json_response({"ok": True}, headers=CORS)

    async def tv_settings(request):
        """The TV's own Art Mode settings (AUG-1722): {"brightness": 6, ...}; the answer is GET /tv/info's."""
        try:
            changes = await request.json()
        except ValueError:
            changes = None
        try:
            return web.json_response(dict(await rotation.set_tv_settings(changes), ok=True), headers=CORS)
        except ValueError as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400, headers=CORS)
        except Exception as e:
            log.info("%s failed (%s: %s)", request.path, type(e).__name__, e)
            return web.json_response({"ok": False, "error": str(e) or type(e).__name__}, status=503, headers=CORS)

    async def settings(request):
        try:
            changes = await request.json()
            if not isinstance(changes, dict):
                raise ValueError("send a JSON object")
            rotation.set_settings(changes)
            events.add("api", "settings", ", ".join("%s=%s" % (k, rotation.cfg.get(k)) for k in sorted(changes)))
        except ValueError as e:
            return web.json_response(dict(rotation.status(), ok=False, error=str(e)), status=400, headers=CORS)
        return web.json_response(dict(rotation.status(), ok=True), headers=CORS)

    async def category(request):
        try:
            return web.json_response(await rotation.gallery(request.query.get("name", "")), headers=CORS)
        except ValueError as e:
            return web.json_response({"ok": False, "error": str(e)}, status=404, headers=CORS)

    thumbs = asyncio.Semaphore(4)  # a page asks for 24 at once; the museums don't like a crowd
    thumb_seconds = 30  # all a thumbnail asks of the network: a slow one doesn't hold the big slot

    async def thumb(request):
        wanted = picture_of(request)
        if not wanted:
            raise web.HTTPNotFound()
        try:
            async with thumbs:
                jpeg = await threads.run_in(threads.FETCHERS, limits.within, thumb_seconds, rotation.thumb, wanted)
        except sources.Skip:
            raise web.HTTPNotFound()
        except Exception as e:
            log.info("no thumbnail for %s (%s: %s)", wanted, type(e).__name__, e)
            raise web.HTTPBadGateway()
        return web.Response(body=jpeg, content_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})

    async def show(request):
        wanted = picture_of(request)
        if not wanted:
            return web.json_response(dict(rotation.status(), ok=False, error="which picture? send ?picture="),
                                     status=400, headers=CORS)
        log.info("asked to show %s", wanted)
        events.add("api", "show", wanted)
        try:
            await wake(request)
            ok = await rotation.choose(wanted)
            return web.json_response(dict(rotation.status(), ok=ok), headers=CORS)
        except ValueError as e:
            return web.json_response(dict(rotation.status(), ok=False, error=str(e)), status=400, headers=CORS)
        except Exception as e:
            log.info("%s failed (%s: %s)", request.path, type(e).__name__, e)
            return web.json_response(dict(rotation.status(), ok=False, error=str(e) or type(e).__name__),
                                     status=503, headers=CORS)

    async def link(request):
        async def go():
            await rotation.stasera.link()
            return True
        return await act(request, go)

    async def unlink(request):
        rotation.stasera.unlink()
        log.info("Stasera unlinked")
        events.add("api", "unlink", "Stasera unlinked")
        return web.json_response(dict(rotation.status(), ok=True), headers=CORS)

    async def never(request):
        wanted = not_the_key(request.query.get("picture")) or rotation.showing_key()
        log.info("asked never to show %s again", wanted)
        events.add("api", "never", wanted)
        return await act(request, lambda: rotation.never(wanted))

    async def artmode(request):
        log.info("asked for Art Mode")
        events.add("api", "artmode", "Art Mode on")
        return await act(request, rotation.art_mode)

    async def saver(request):
        try:
            minutes = min(max(int(request.query.get("minutes", "")), 1), 1440)
        except ValueError:
            minutes = None  # an older Frame TV: the interval
        log.info("Frame TV's screensaver started%s", ", a new picture every %d min" % minutes if minutes else "")
        events.add("api", "saver", "the screensaver started%s" % (", a new picture every %d min" % minutes
                                                                    if minutes else ""))
        return await act(request, lambda: rotation.start_saver(minutes))

    heard = collections.deque(maxlen=1000)  # Frame TV sends an event again when the answer didn't reach it

    async def app_event(request):
        """Frame TV's events, sent when they happened or later from its queue: the time is Frame TV's."""
        try:
            body = await request.json()
            got = body.get("events") if isinstance(body, dict) else None
            if not isinstance(got, list):
                raise ValueError
        except ValueError:
            return web.json_response({"ok": False, "error": 'send {"events": [...]}'}, status=400, headers=CORS)
        now = time.time()
        for e in got[:APP_EVENTS]:
            if not isinstance(e, dict) or not e.get("kind") or (e.get("n") and e["n"] in heard):
                continue
            heard.append(e.get("n"))
            try:
                at = float(e.get("at")) / 1000
            except (TypeError, ValueError):
                at = now
            if not now - events.KEEP_DAYS * 86400 < at <= now + 60:
                at = now  # the TV's clock is off, or it's too old
            late = now - at
            events.add("app", str(e.get("kind") or "?")[:40], str(e.get("detail") or "")[:300],
                       why="Frame TV" + (", sent %d min later" % (late // 60) if late >= 120 else ""), at=at)
        return web.json_response({"ok": True, "n": min(len(got), APP_EVENTS)}, headers=CORS)

    async def event_log(request):
        try:
            after, until = int(request.query.get("since") or 0), int(request.query.get("until") or 0) or None
            limit = min(max(int(request.query.get("limit") or events.LIMIT), 1), events.LIMIT)
        except ValueError:
            return web.json_response({"ok": False, "error": "since, until and limit are numbers"}, status=400,
                                     headers=CORS)
        got, more = events.since(after, until, limit)
        return web.json_response({"events": got, "more": more}, headers=CORS)

    async def export(request):
        got, _ = events.since(0, None, limit=10 ** 9)
        name = "frame-art-events-%s.json" % time.strftime("%Y-%m-%d")
        return web.Response(text=json.dumps(got, ensure_ascii=False, indent=1), content_type="application/json",
                            headers=dict(CORS, **{"Content-Disposition": 'attachment; filename="%s"' % name}))

    async def page(request):
        text = PAGE.replace("/*STRINGS*/{}", json.dumps(i18n.PAGE, ensure_ascii=False))
        return web.Response(text=text, content_type="text/html")

    async def picture(request):
        if not os.path.exists(rotation.showing_path):
            raise web.HTTPNotFound()
        return web.FileResponse(rotation.showing_path, headers={"Cache-Control": "no-cache"})

    async def options(request):
        return web.Response(headers=CORS)

    a = web.Application(middlewares=[keyed])
    a.add_routes([web.get("/", page), web.get("/showing.jpg", picture), web.get("/status", status),
                  web.get("/category", category), web.get("/thumb", thumb), web.get("/tv", tv),
                  web.get("/tv/info", tv_info), web.post("/tv/settings", tv_settings),
                  web.post("/tv/report", tv_report), web.post("/tv/on", tv_on),
                  web.post("/tv/off", tv_off),
                  web.get("/events", event_log), web.get("/events/export", export), web.post("/event", app_event),
                  web.post("/show", show),
                  web.post("/next", next_), web.post("/artmode", artmode), web.post("/never", never),
                  web.post("/settings", settings), web.post("/schedule", settings), web.post("/saver", saver),
                  web.post("/stasera/link", link), web.post("/stasera/unlink", unlink),
                  web.route("OPTIONS", "/{tail:.*}", options)])
    return a


async def serve(rotation, port):
    runner = web.AppRunner(app(rotation), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("API on port %d", port)


