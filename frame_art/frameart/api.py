"""A small HTTP API on the home network, for Home Assistant (rest_command) and Frame TV on the TV.

GET  /         a page with what's showing, the buttons, the mode and the categories, the schedule and Stasera (the
               add-on's page in Home Assistant, through ingress)
GET  /status   what's showing, when it changed and when it changes next, the mode, the categories, how many pictures
               each source has, the settings and Stasera
GET  /showing.jpg  the picture
GET  /category?name=Japan  for choosing a picture: what's been on the wall lately and 24 at random
GET  /thumb?key=…  a small copy of a picture (a key from /category)
POST /next     a new picture now; ?art_mode=1 puts the TV in Art Mode too; ?what=morning or ?what=tonight shows
               Morgenbildet or tonight's show instead of one from the rotation. Ends a fixed picture.
POST /show?key=…  that picture now, in Art Mode, standing until the next Morgenbildet (Fast bilde)
POST /artmode  Art Mode on, with the picture it has
POST /settings JSON with what to change: mode (shuffle or category), category, categories_off (a list, for Shuffle),
               interval_minutes, morning, morning_time, tonight, tonight_time, screensaver_stasera, music,
               music_home_only. A new mode or category ends a fixed picture. /schedule is the same.
POST /stasera/link    a code to approve in Stasera (in /status under pairing until it's approved)
POST /stasera/unlink  forgets the Stasera token

No login: it's for the home network, like the TV's own API. The answers wait for the TV (up to a minute or two).
"""
import asyncio
import logging
import os

from aiohttp import web

from . import sources

log = logging.getLogger(__name__)

with open(os.path.join(os.path.dirname(__file__), "page.html"), encoding="utf-8") as f:
    PAGE = f.read()  # the add-on's page

CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type"}


def app(rotation):
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
        return await act(request, lambda: rotation.change(art_mode=art_mode, what=what))

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

    async def artmode(request):
        log.info("asked for Art Mode")
        return await act(request, rotation.art_mode)

    async def page(request):
        return web.Response(text=PAGE, content_type="text/html")

    async def picture(request):
        if not os.path.exists(rotation.showing_path):
            raise web.HTTPNotFound()
        return web.FileResponse(rotation.showing_path, headers={"Cache-Control": "no-cache"})

    async def options(request):
        return web.Response(headers=CORS)

    a = web.Application()
    a.add_routes([web.get("/", page), web.get("/showing.jpg", picture), web.get("/status", status),
                  web.get("/category", category), web.get("/thumb", thumb), web.post("/show", show),
                  web.post("/next", next_), web.post("/artmode", artmode), web.post("/settings", settings),
                  web.post("/schedule", settings),
                  web.post("/stasera/link", link), web.post("/stasera/unlink", unlink),
                  web.route("OPTIONS", "/{tail:.*}", options)])
    return a


async def serve(rotation, port):
    runner = web.AppRunner(app(rotation), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("API on port %d", port)


