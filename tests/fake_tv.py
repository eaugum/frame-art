"""A fake Frame TV on 127.0.0.1 for tests/serve_page.py and the tests: what frameart/tv.py asks of the real one.

Port 8002 (TLS, a self-made certificate; the client doesn't check it) has the art channel and the REST answer
samsungtvws asks for when it connects; port 8001 (plain) has the REST answer the add-on's powered_on() reads. An upload
comes in on a second, plain socket, as the TV does it. Not covered: the remote channel's keys (they're only
recorded), thumbnails, mattes and the TV's own slideshow. Nothing leaves this machine.
"""
import asyncio
import json
import logging
import os
import random
import ssl
import subprocess
import tempfile

from aiohttp import WSMsgType, web

log = logging.getLogger(__name__)

TOKEN = "FAKE-TV-TOKEN-0000"


class FakeTV:
    """started with start(); .uploads, .selected, .deleted and .commands record what it got."""

    def __init__(self, art_mode="on", rest_port=8001, ws_port=8002):
        self.art_mode = art_mode
        self.rest_port, self.ws_port = rest_port, ws_port
        self.photos = []  # content_ids, as "MY-C0002"
        self.uploads, self.selected, self.deleted, self.commands = [], [], [], []
        self.current = None
        self._sockets = []

    async def start(self, host="127.0.0.1"):
        app = web.Application()
        app.add_routes([web.get("/api/v2/", self._device), web.get("/api/v2/channels/{app}", self._channel)])
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, host, self.rest_port).start()
        await web.TCPSite(self._runner, host, self.ws_port, ssl_context=self._tls()).start()
        self._upload_server = await asyncio.start_server(self._receive, host, 0)
        self.upload_port = self._upload_server.sockets[0].getsockname()[1]
        log.info("fake TV: art channel on %s:%d, REST on %d, uploads on %d", host, self.ws_port, self.rest_port,
                 self.upload_port)

    async def stop(self):
        self._upload_server.close()
        for ws in list(self._sockets):
            await ws.close()
        await self._runner.cleanup()

    def _tls(self):
        d = tempfile.mkdtemp(prefix="fake-tv-")
        crt, key = os.path.join(d, "tv.crt"), os.path.join(d, "tv.key")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                        "-nodes", "-subj", "/CN=fake-tv", "-days", "2", "-keyout", key, "-out", crt],
                       check=True, capture_output=True)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(crt, key)
        return ctx

    async def _device(self, request):
        # a 2022 model: samsungtvws then doesn't open the remote channel to fetch a token
        return web.json_response({"device": {"model": "22_FAKE_FRAME", "name": "Fake Frame", "PowerState": "on",
                                             "FrameTVSupport": "true"}})

    async def _channel(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._sockets.append(ws)
        art = request.match_info["app"] == "com.samsung.art-app"
        await ws.send_json({"event": "ms.channel.connect", "data": {"token": TOKEN}})
        if art:
            await ws.send_json({"event": "ms.channel.ready"})
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            body = json.loads(msg.data)
            params = body.get("params") or {}
            if art and params.get("event") == "art_app_request":
                await self._art_request(ws, json.loads(params["data"]))
            else:
                self.commands.append(body)
                log.info("fake TV: %s got %s", request.match_info["app"], body)
        self._sockets.remove(ws)
        return ws

    async def _art_request(self, ws, req):
        name = req["request"]
        log.info("fake TV: art request %s", {k: v for k, v in req.items() if k not in ("id", "request_id")})
        self.commands.append(req)
        reply = {"request_id": req.get("request_id"), "id": req.get("id"), "event": name}
        if name in ("get_artmode_status", "set_artmode_status"):
            if name == "set_artmode_status":
                self.art_mode = req["value"]
            reply.update(event="artmode_status", value=self.art_mode, status=self.art_mode)
        elif name == "get_content_list":
            reply["content_list"] = json.dumps([{"content_id": c, "category_id": req.get("category")}
                                                for c in self.photos])
        elif name == "send_image":
            self._key = "%08x" % random.getrandbits(32)
            reply.update(event="ready_to_use", conn_info=json.dumps(
                {"ip": "127.0.0.1", "port": self.upload_port, "key": self._key, "secured": False}))
            self._waiting = ws
        elif name == "select_image":
            self.current = req["content_id"]
            self.selected.append({"content_id": self.current, "show": req.get("show")})
            log.info("fake TV: %s %s", "showing" if req.get("show") else "ready for Art Mode:", self.current)
            reply["event"] = "image_selected"
        elif name == "delete_image_list":
            gone = [c["content_id"] for c in req["content_id_list"]]
            self.photos = [c for c in self.photos if c not in gone]
            self.deleted += gone
            log.info("fake TV: deleted %s", gone)
            reply["event"] = "image_deleted"
        elif name == "get_current_artwork":
            reply["content_id"] = self.current
        elif name in ("get_api_version", "api_version"):
            reply["version"] = "4.3.4.0"
        elif name == "get_slideshow_status":
            reply.update(value="off", type="shuffleslideshow", category_id="MY-C0002")
        elif name == "get_artmode_settings":
            reply["data"] = json.dumps([
                {"item": "brightness", "value": "5", "min": "1", "max": "10"},
                {"item": "color_temperature", "value": "0", "min": "-5", "max": "5"},
                {"item": "motion_sensitivity", "value": "2", "min": "1", "max": "3"},
                {"item": "motion_timer", "value": "60", "valid_values": json.dumps(["off", "5", "15", "60"])},
                {"item": "brightness_sensor_setting", "value": "off"}])
        elif name == "get_device_info":
            reply.update(model="22_FAKE_FRAME", device_name="Fake Frame")
        await ws.send_json({"event": "d2d_service_message", "data": json.dumps(reply)})

    async def _receive(self, reader, writer):
        """An upload: 4 bytes of header length, the header (JSON), then fileLength bytes."""
        try:
            header = json.loads(await reader.readexactly(int.from_bytes(await reader.readexactly(4), "big")))
            body = await reader.readexactly(int(header["fileLength"]))
        finally:
            writer.close()
        if header.get("secKey") != self._key:
            log.warning("fake TV: an upload with the wrong key")
            return
        content_id = "MY_F%04d" % (len(self.uploads) + 1)
        self.photos.append(content_id)
        self.uploads.append({"content_id": content_id, "bytes": len(body), "file_type": header["fileType"]})
        log.info("fake TV: got a %s upload, %d bytes, as %s", header["fileType"], len(body), content_id)
        await asyncio.sleep(0.05)  # the client starts waiting for image_added once it has written
        await self._waiting.send_json({"event": "d2d_service_message", "data": json.dumps(
            {"event": "image_added", "content_id": content_id})})
