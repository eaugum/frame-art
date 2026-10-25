"""A small HTTP API on the home network, for Home Assistant (rest_command) and Frame TV on the TV.

GET  /         a page with what's showing and two buttons (the add-on's page in Home Assistant, through ingress)
GET  /status   what's showing, when it changed and when it changes next, and how many pictures each source has
GET  /showing.jpg  the picture
POST /next     a new picture now; ?art_mode=1 puts the TV in Art Mode too
POST /artmode  Art Mode on, with the picture it has

No login: it's for the home network, like the TV's own API. The answers wait for the TV (up to a minute or two).
"""
import logging
import os

from aiohttp import web

log = logging.getLogger(__name__)

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
        log.info("asked for a new picture%s", " in Art Mode" if art_mode else "")
        return await act(request, lambda: rotation.change(art_mode=art_mode))

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
                  web.post("/next", next_), web.post("/artmode", artmode), web.route("OPTIONS", "/{tail:.*}", options)])
    return a


async def serve(rotation, port):
    runner = web.AppRunner(app(rotation), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("API on port %d", port)


# Relative paths: through ingress the page lives under /api/hassio_ingress/<token>/.
PAGE = """<!doctype html>
<html lang="nb"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Frame Art</title>
<style>
  body { font: 16px/1.4 system-ui, sans-serif; margin: 0; padding: 24px; background: #111; color: #eee; }
  main { max-width: 760px; margin: 0 auto; }
  img { width: 100%; aspect-ratio: 16 / 9; object-fit: cover; background: #222; border-radius: 6px; display: block; }
  h1 { font-size: 20px; margin: 16px 0 4px; }
  p { color: #aaa; margin: 0 0 16px; }
  button { font: inherit; padding: 12px 20px; margin: 0 8px 8px 0; border: 0; border-radius: 6px; cursor: pointer;
           background: #f2c94c; color: #111; }
  button.second { background: #333; color: #eee; }
  button:disabled { opacity: .5; cursor: default; }
  h2 { font-size: 15px; margin: 24px 0 8px; color: #aaa; font-weight: 600; }
  table { border-collapse: collapse; width: 100%; color: #ccc; }
  td { padding: 4px 0; border-top: 1px solid #222; }
  td.n { text-align: right; color: #888; }
</style></head>
<body><main>
  <img id="pic" alt="">
  <h1 id="title">…</h1>
  <p id="info"></p>
  <button id="next">Nytt bilde i Kunstmodus</button>
  <button id="art" class="second">Slå på Kunstmodus</button>
  <p id="msg"></p>
  <h2>Kildene</h2>
  <table id="sources"></table>
</main>
<script>
  function $(id) { return document.getElementById(id); }
  function time(s) { return s ? new Date(s * 1000).toLocaleTimeString("nb-NO", {hour: "2-digit", minute: "2-digit"}) : "–"; }
  function show(s) {
    var label = s.showing || "";
    $("title").textContent = label.indexOf(": ") < 0 ? (label || "Ikke byttet ennå") : label.slice(label.indexOf(": ") + 2);
    $("info").textContent = (label.indexOf(": ") < 0 ? "" : label.split(": ")[0] + " · ") +
      "byttet " + time(s.changed) + " · neste " + time(s.next) + " · versjon " + s.version;
    $("pic").src = "showing.jpg?" + s.changed;
    $("next").disabled = $("art").disabled = !!s.busy;
    var rows = "";
    (s.sources || []).forEach(function (name) {
      var n = (s.pools || {})[name];
      rows += "<tr><td></td><td class=n>" + (n ? n + " bilder" : "ingen ennå") + "</td></tr>";
    });
    $("sources").innerHTML = rows;
    (s.sources || []).forEach(function (name, i) { $("sources").rows[i].cells[0].textContent = name; });
  }
  function load() { fetch("status").then(function (r) { return r.json(); }).then(show).catch(function () {}); }
  function act(path, doing) {
    $("next").disabled = $("art").disabled = true;
    $("msg").textContent = doing;
    fetch(path, {method: "POST"}).then(function (r) { return r.json(); }).then(function (s) {
      show(s);
      $("msg").textContent = s.ok ? "Ferdig." : "TV-en svarte ikke: " + (s.error || "ukjent feil");
    }).catch(function () { $("msg").textContent = "Fikk ikke svar."; load(); });
  }
  $("next").onclick = function () { act("next?art_mode=1", "Henter et nytt bilde og sender det til TV-en …"); };
  $("art").onclick = function () { act("artmode", "Slår på Kunstmodus …"); };
  load();
  setInterval(load, 30000);
</script>
</body></html>
"""
