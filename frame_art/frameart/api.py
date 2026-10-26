"""A small HTTP API on the home network, for Home Assistant (rest_command) and Frame TV on the TV.

GET  /         a page with what's showing, the buttons, the schedule and Stasera (the add-on's page in Home Assistant,
               through ingress)
GET  /status   what's showing, when it changed and when it changes next, how many pictures each source has, the
               schedule and Stasera
GET  /showing.jpg  the picture
POST /next     a new picture now; ?art_mode=1 puts the TV in Art Mode too; ?what=morning or ?what=tonight shows
               Morgenbildet or tonight's show instead of one from the rotation
POST /artmode  Art Mode on, with the picture it has
POST /schedule JSON with what to change: interval_minutes, morning, morning_time, tonight, tonight_time
POST /stasera/link    a code to approve in Stasera (in /status under pairing until it's approved)
POST /stasera/unlink  forgets the Stasera token

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
        what = request.query.get("what") or None
        if what not in (None, "morning", "tonight"):
            return web.json_response({"ok": False, "error": "what is morning or tonight"}, status=400, headers=CORS)
        log.info("asked for %s%s", what or "a new picture", " in Art Mode" if art_mode else "")
        return await act(request, lambda: rotation.change(art_mode=art_mode, what=what))

    async def schedule(request):
        try:
            rotation.set_schedule(await request.json())
        except ValueError as e:
            return web.json_response(dict(rotation.status(), ok=False, error=str(e)), status=400, headers=CORS)
        return web.json_response(dict(rotation.status(), ok=True), headers=CORS)

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
                  web.post("/next", next_), web.post("/artmode", artmode), web.post("/schedule", schedule),
                  web.post("/stasera/link", link), web.post("/stasera/unlink", unlink),
                  web.route("OPTIONS", "/{tail:.*}", options)])
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
  label { display: flex; align-items: center; gap: 12px; padding: 6px 0; border-top: 1px solid #222; color: #ccc; }
  label span { flex: 1; }
  input { font: inherit; background: #222; color: #eee; border: 1px solid #333; border-radius: 6px; padding: 6px 8px; }
  input[type=number] { width: 80px; } input[type=checkbox] { width: 20px; height: 20px; }
  a { color: #f2c94c; }
</style></head>
<body><main>
  <img id="pic" alt="">
  <h1 id="title">…</h1>
  <p id="info"></p>
  <button id="next">Nytt bilde i Kunstmodus</button>
  <button id="art" class="second">Slå på Kunstmodus</button>
  <button id="morning" class="second">Vis Morgenbildet</button>
  <button id="tonight" class="second">Vis kveldens serie</button>
  <p id="msg"></p>
  <h2>Tidsplan</h2>
  <label><span>Bytt bilde hvert</span><input id="interval_minutes" type="number" min="5" max="1440"> min</label>
  <label><span>Morgenbildet (dato og vær)</span><input id="morning_on" type="checkbox"><input id="morning_time" type="time"></label>
  <label><span>Kveldens serie fra Stasera</span><input id="tonight_on" type="checkbox"><input id="tonight_time" type="time"></label>
  <p id="saved"></p>
  <h2>Stasera</h2>
  <p id="stasera"></p>
  <button id="link" class="second">Koble til Stasera</button>
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
    busy(!!s.busy);
    var sc = s.schedule || {};
    if (document.activeElement.tagName !== "INPUT") {
      $("interval_minutes").value = sc.interval_minutes;
      $("morning_on").checked = !!sc.morning; $("morning_time").value = sc.morning_time || "";
      $("tonight_on").checked = !!sc.tonight; $("tonight_time").value = sc.tonight_time || "";
    }
    var p = s.pairing;
    $("stasera").innerHTML = "";
    if (s.stasera === "off") $("stasera").textContent = "Av: stasera_url mangler i valgene til add-on-et.";
    else if (s.stasera === "linked") $("stasera").textContent = "Koblet. Kveldens serie kommer fra «I kveld».";
    else if (p) {
      $("stasera").append("Godkjenn koden ", Object.assign(document.createElement("b"), {textContent: p.code}), " i ",
        Object.assign(document.createElement("a"), {href: p.url, target: "_blank", textContent: "Stasera"}), ".");
    } else $("stasera").textContent = "Ikke koblet.";
    $("link").textContent = s.stasera === "linked" ? "Koble fra" : "Koble til Stasera";
    $("link").hidden = s.stasera === "off" || !!p;
    var rows = "";
    (s.sources || []).forEach(function (name) {
      var n = (s.pools || {})[name];
      rows += "<tr><td></td><td class=n>" + (n === null || n === undefined ? "ikke lest ennå (første gang den trekkes)" : n ? n + " bilder" : "ingen bilder funnet") + "</td></tr>";
    });
    $("sources").innerHTML = rows;
    (s.sources || []).forEach(function (name, i) { $("sources").rows[i].cells[0].textContent = name; });
  }
  function busy(b) { ["next", "art", "morning", "tonight"].forEach(function (id) { $(id).disabled = b; }); }
  function load() { fetch("status").then(function (r) { return r.json(); }).then(show).catch(function () {}); }
  function act(path, doing) {
    busy(true);
    $("msg").textContent = doing;
    fetch(path, {method: "POST"}).then(function (r) { return r.json(); }).then(function (s) {
      show(s);
      $("msg").textContent = s.ok ? "Ferdig." : "TV-en svarte ikke: " + (s.error || "ukjent feil");
    }).catch(function () { $("msg").textContent = "Fikk ikke svar."; load(); });
  }
  $("next").onclick = function () { act("next?art_mode=1", "Henter et nytt bilde og sender det til TV-en …"); };
  $("art").onclick = function () { act("artmode", "Slår på Kunstmodus …"); };
  $("morning").onclick = function () { act("next?art_mode=1&what=morning", "Lager Morgenbildet …"); };
  $("tonight").onclick = function () { act("next?art_mode=1&what=tonight", "Lager plakaten for kveldens serie …"); };
  function save(changes) {
    fetch("schedule", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(changes)})
      .then(function (r) { return r.json(); }).then(function (s) {
        $("saved").textContent = s.ok ? "Lagret." : "Ikke lagret: " + s.error;
        document.activeElement.blur();
        show(s);
      }).catch(function () { $("saved").textContent = "Fikk ikke lagret."; });
  }
  $("interval_minutes").onchange = function () { save({interval_minutes: +this.value}); };
  $("morning_on").onchange = function () { save({morning: this.checked}); };
  $("morning_time").onchange = function () { if (this.value) save({morning_time: this.value}); };
  $("tonight_on").onchange = function () { save({tonight: this.checked}); };
  $("tonight_time").onchange = function () { if (this.value) save({tonight_time: this.value}); };
  $("link").onclick = function () {
    var linked = this.textContent === "Koble fra";
    fetch(linked ? "stasera/unlink" : "stasera/link", {method: "POST"}).then(function (r) { return r.json(); })
      .then(function (s) { show(s); if (!s.ok) $("stasera").textContent = s.error || "Fikk ikke svar fra Stasera."; });
  };
  load();
  setInterval(load, 30000);
  setInterval(function () { if ($("stasera").querySelector("b")) load(); }, 3000);  // waiting for the code
</script>
</body></html>
"""
