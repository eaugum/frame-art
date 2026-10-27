"""A small HTTP API on the home network, for Home Assistant (rest_command) and Frame TV on the TV.

GET  /         a page with what's showing, the buttons, the sources to tick, the settings and Stasera (the
               add-on's page in Home Assistant, through ingress)
GET  /status   what's showing, when it changed and when it changes next, the mode, the categories, how many pictures
               each source has (null: not read yet; reading says some are being read), the settings and Stasera
GET  /showing.jpg  the picture
GET  /category?name=Japan  for choosing a picture: what's been on the wall lately and 24 at random, from the
               category's sources that are ticked
GET  /thumb?key=…  a small copy of a picture (a key from /category)
GET  /tv       whether the TV is off ({"off": true}), from tv_entity; null without one
POST /tv/on    the TV on through Home Assistant (tv_entity), then back_app opened, without waiting for the TV's turn
POST /next     a new picture now; ?art_mode=1 puts the TV in Art Mode too; ?what=morning or ?what=tonight shows
               Morgenbildet or tonight's show instead of one from the rotation. Ends a fixed picture. ?wake=1 (and on
               /show) turns the TV on first through Home Assistant when it's off.
POST /show?key=…  that picture now, in Art Mode, standing until the next morning picture (a fixed picture)
POST /artmode  Art Mode on, with the picture it has
POST /never    what's on the wall (from a source; showing_key in /status) is never drawn again, and another comes
POST /settings JSON with what to change: sources_off (the sources not ticked), interval_minutes, keep,
               morning, morning_time, morning_tv_on, tonight, tonight_time, tonight_tv_on, screensaver,
               screensaver_stasera, music, music_home_only (the music and turning the TV on); mode shuffle ends a fixed picture, and mode category with category ticks only that
               category's sources. New sources_off ends a fixed picture too. /schedule is the same.
POST /stasera/link    a code to approve in Stasera (in /status under pairing until it's approved)
POST /stasera/unlink  forgets the Stasera token

POST /saver    Frame TV's screensaver started: Art Mode on, with what we watch in Stasera when screensaver_stasera is
               on, until Art Mode goes off (AUG-1494); ?minutes=5 changes the picture that often meanwhile

Every call from outside needs the add-on's key (AUG-1496), as "Authorization: Bearer <key>" or ?key=<key>: it's
api_key in the add-on's options (made and written there when it's empty). The page itself, through ingress, doesn't
need it. The answers wait for the TV (up to a minute or two).
"""
import asyncio
import hmac
import json
import logging
import os
import secrets
import urllib.request

from aiohttp import web

from . import i18n, sources

log = logging.getLogger(__name__)

with open(os.path.join(os.path.dirname(__file__), "page.html"), encoding="utf-8") as f:
    PAGE = f.read()  # the add-on's page

CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization"}
INGRESS = "172.30.32.2"  # the Supervisor, when the page is opened in Home Assistant


def api_key(cfg, data_dir):
    """The key Frame TV and others send: api_key in the options. Without one, the key made before (api_key.txt) or a
    new one, written into the add-on's options so it can be read there."""
    if (cfg.get("api_key") or "").strip():
        return cfg["api_key"].strip()
    path = os.path.join(data_dir, "api_key.txt")
    try:
        with open(path) as f:
            key = f.read().strip()
    except OSError:
        key = ""
    if not key:
        key = secrets.token_urlsafe(24)
        with open(path, "w") as f:
            f.write(key)
        os.chmod(path, 0o600)
        log.info("made a new key for the API")
    _into_options(data_dir, key)
    return key


def _into_options(data_dir, key):
    """api_key into the add-on's own options, through the Supervisor (hassio_api)."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return
    try:
        with open(os.path.join(data_dir, "options.json")) as f:
            options = json.load(f)
        req = urllib.request.Request("http://supervisor/addons/self/options", method="POST",
                                     data=json.dumps({"options": dict(options, api_key=key)}).encode(),
                                     headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10):
            pass
        log.info("the API's key is now in the add-on's options (api_key)")
    except Exception as e:
        log.warning("couldn't write the API's key into the options (%s: %s); it's in %s/api_key.txt",
                    type(e).__name__, e, data_dir)


def app(rotation):
    key = api_key(rotation.cfg, rotation.data)

    def ingress(request):
        return request.remote == INGRESS

    @web.middleware
    async def keyed(request, handler):
        if request.method == "OPTIONS" or (request.method == "GET" and request.path == "/") or ingress(request):
            return await handler(request)
        given = request.headers.get("Authorization", "")
        given = given[7:] if given.startswith("Bearer ") else request.query.get("key", "")
        if not hmac.compare_digest(given.encode(), key.encode()):
            return web.json_response({"ok": False, "error": "wrong or no key (see the add-on's page)"}, status=401,
                                     headers=CORS)
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

        async def go():
            await wake(request)
            return await rotation.change(art_mode=art_mode, what=what)
        return await act(request, go)

    async def wake(request):
        """?wake=1: the TV on first, when it's off (the page asked)."""
        if request.query.get("wake") == "1" and await rotation.tv_off():
            await rotation.turn_on()

    async def tv_on(request):
        log.info("asked to turn the TV on")
        return await act(request, rotation.wake_up)

    async def tv(request):
        return web.json_response({"off": await rotation.tv_off()}, headers=CORS)

    async def settings(request):
        try:
            changes = await request.json()
            if not isinstance(changes, dict):
                raise ValueError("send a JSON object")
            rotation.set_settings(changes)
        except ValueError as e:
            return web.json_response(dict(rotation.status(), ok=False, error=str(e)), status=400, headers=CORS)
        return web.json_response(dict(rotation.status(), ok=True), headers=CORS)

    async def category(request):
        try:
            return web.json_response(await rotation.gallery(request.query.get("name", "")), headers=CORS)
        except ValueError as e:
            return web.json_response({"ok": False, "error": str(e)}, status=404, headers=CORS)

    thumbs = asyncio.Semaphore(4)  # a page asks for 24 at once; the museums don't like a crowd

    async def thumb(request):
        key = request.query.get("key", "")
        try:
            async with thumbs:
                jpeg = await asyncio.to_thread(rotation.thumb, key)
        except sources.Skip:
            raise web.HTTPNotFound()
        except Exception as e:
            log.info("no thumbnail for %s (%s: %s)", key, type(e).__name__, e)
            raise web.HTTPBadGateway()
        return web.Response(body=jpeg, content_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})

    async def show(request):
        key = request.query.get("key", "")
        log.info("asked to show %s", key)
        try:
            await wake(request)
            ok = await rotation.choose(key)
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
        return web.json_response(dict(rotation.status(), ok=True), headers=CORS)

    async def never(request):
        log.info("asked never to show %s again", rotation.showing_key())
        return await act(request, rotation.never)

    async def artmode(request):
        log.info("asked for Art Mode")
        return await act(request, rotation.art_mode)

    async def saver(request):
        try:
            minutes = min(max(int(request.query.get("minutes", "")), 1), 1440)
        except ValueError:
            minutes = None  # an older Frame TV: the interval
        log.info("Frame TV's screensaver started%s", ", a new picture every %d min" % minutes if minutes else "")
        return await act(request, lambda: rotation.start_saver(minutes))

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
                  web.get("/category", category), web.get("/thumb", thumb), web.get("/tv", tv), web.post("/tv/on", tv_on),
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


