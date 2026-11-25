"""AUG-1772: /show and /thumb take only keys the add-on offered, and a folder source opens only its own regular files."""
import asyncio
import http.server
import json
import os
import threading
import time
import unittest
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

import fakes
from frameart import api, sources
from test_smoke import Temp

KEY = {"Authorization": "Bearer " + fakes.FAKE_KEY}


class Recorder(http.server.ThreadingHTTPServer):
    """A local server that answers every GET with a small JSON and keeps the paths asked."""

    def __init__(self):
        self.asked = []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                server.asked.append(self.path)
                body = json.dumps({"orderedItems": [{"id": "http://127.0.0.1:%d/object/1" % server.port}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        super().__init__(("127.0.0.1", 0), Handler)
        self.port = self.server_address[1]
        threading.Thread(target=self.serve_forever, daemon=True).start()


class Setup(Temp):
    def setUp(self):
        super().setUp()
        self.museum = Recorder()
        self.addCleanup(self.museum.server_close)
        self.addCleanup(self.museum.shutdown)
        # outside the folder: a good 16:9 picture next to it, which a forged key must not reach
        fakes.pictures(os.path.join(os.path.dirname(self.pictures), "elsewhere"), n=1)
        self.outside = os.path.join(os.path.dirname(self.pictures), "elsewhere", "sample-1.jpg")

    def rotation(self, **more):
        service = {"name": "museum", "url": "http://127.0.0.1:%d/search?q={query}" % self.museum.port,
                   "items": "orderedItems", "steps": ["{id}"], "image": "{step1.image}", "thumb": "{step1.thumb}"}
        sources_ = [{"category": "My pictures", "name": "My pictures", "type": "folder", "query": self.pictures},
                    {"name": "Museum", "type": "museum"}]
        return super().rotation(services=[service], sources=sources_, **more)

    FORGED = ["My pictures:../elsewhere/sample-1.jpg", None, "My pictures:sample-9.jpg", "Museum:http://127.0.0.1:%d/x"]

    def forged(self):
        keys = list(self.FORGED)
        keys[1] = "My pictures:" + self.outside
        keys[3] = keys[3] % self.museum.port
        return keys


class KeysTest(Setup):
    def test_thumb_takes_only_offered_keys(self):
        rot = self.rotation()
        rot.pool(rot.by_name["My pictures"])
        fakes.pictures(self.pictures, n=9)  # sample-9.jpg is there now, but was never listed
        for key in self.forged():
            with self.subTest(key=key):
                with self.assertRaises(sources.Skip):
                    rot.thumb(key)
        self.assertEqual(self.museum.asked, [])
        self.assertTrue(rot.thumb("My pictures:sample-1.jpg").startswith(b"\xff\xd8"))

    def test_thumb_checks_before_the_cache(self):
        rot = self.rotation()
        forged = "My pictures:" + self.outside
        os.makedirs(rot.thumbs, exist_ok=True)
        with open(rot._thumb_path(forged), "wb") as f:
            f.write(b"\xff\xd8 cached")
        with self.assertRaises(sources.Skip):
            rot.thumb(forged)

    def test_history_and_fixed_are_offered(self):
        rot = self.rotation()
        fakes.pictures(self.pictures, n=5)
        rot.state["history"] = [{"key": "My pictures:sample-4.jpg", "label": "x", "at": 1}]
        rot.cfg["fixed"] = {"key": "My pictures:sample-5.jpg", "label": "y", "until": time.time() + 3600}
        self.assertTrue(rot.thumb("My pictures:sample-4.jpg").startswith(b"\xff\xd8"))
        self.assertTrue(rot.thumb("My pictures:sample-5.jpg").startswith(b"\xff\xd8"))

    def test_choose_refuses_forged_keys_before_the_source(self):
        rot = self.rotation()
        rot.pool(rot.by_name["My pictures"])
        put = mock.AsyncMock()
        with mock.patch.object(rot, "_put", put):
            for key in self.forged():
                with self.subTest(key=key):
                    with self.assertRaises(ValueError):
                        asyncio.run(rot.choose(key))
            self.assertTrue(asyncio.run(rot.choose("My pictures:sample-2.jpg")))
        self.assertEqual(self.museum.asked, [])
        self.assertEqual(put.await_count, 1)
        self.assertEqual(rot.cfg["fixed"]["key"], "My pictures:sample-2.jpg")

    def test_every_offered_key_can_be_chosen(self):
        rot = self.rotation()
        rot.state["history"] = [{"key": "My pictures:sample-3.jpg", "label": "My pictures: sample-3.jpg", "at": 1}]

        async def gallery():
            await rot.gallery("My pictures")
            await asyncio.sleep(0.5)  # the listing in the background
            return await rot.gallery("My pictures")

        got = asyncio.run(gallery())
        keys = [g["key"] for g in got["recent"] + got["random"]]
        self.assertEqual(len(set(keys)), 3)
        for key in keys:
            self.assertTrue(rot.thumb(key).startswith(b"\xff\xd8"), key)

    def test_old_state_with_a_forged_fixed_key_still_starts(self):
        with open(os.path.join(self.data, "settings.json"), "w") as f:
            json.dump({"fixed": {"key": "My pictures:../../etc/passwd", "label": "x", "until": time.time() + 60}}, f)
        with open(os.path.join(self.data, "state.json"), "w") as f:
            json.dump({"history": [{"key": "My pictures:/etc/hostname", "label": "x", "at": 1}],
                       "pools": {"My pictures": {"at": 1, "keys": ["../x.jpg"], "wide": True}}}, f)
        rot = self.rotation()
        self.assertEqual(rot.wanted(), "fixed")
        with self.assertRaises(sources.Skip):
            rot.thumb("My pictures:../x.jpg")  # listed once, but not inside the folder
        jpeg, label, key = rot.pick()
        self.assertTrue(key.startswith("My pictures:sample-") or key.startswith("Museum:"), key)


class ApiKeysTest(Setup, unittest.IsolatedAsyncioTestCase):
    async def test_api_refuses_forged_keys(self):
        rot = self.rotation()
        rot.pool(rot.by_name["My pictures"])
        client = TestClient(TestServer(api.app(rot)))
        await client.start_server()
        try:
            for key in self.forged():
                with self.subTest(key=key):
                    r = await client.get("/thumb", params={"key": key}, headers=KEY)
                    self.assertEqual(r.status, 404)
                    r = await client.post("/show", params={"key": key}, headers=KEY)
                    self.assertEqual(r.status, 400)
                    self.assertNotIn("No such file", (await r.json())["error"])
            r = await client.get("/thumb", params={"key": "My pictures:sample-1.jpg"}, headers=KEY)
            self.assertEqual(r.status, 200)
        finally:
            await client.close()
        self.assertEqual(self.museum.asked, [])


class FolderTest(Temp):
    def folder(self):
        return sources.Folder({"name": "My pictures", "query": self.pictures}, {})

    def test_only_inside_the_folder(self):
        fakes.pictures(os.path.join(self.data, "elsewhere"), n=1)
        outside = os.path.join(self.data, "elsewhere", "sample-1.jpg")
        folder = self.folder()
        for key in (os.path.relpath(outside, self.pictures), outside, "sub/../../data/elsewhere/sample-1.jpg"):
            with self.subTest(key=key):
                with self.assertRaises(sources.Skip):
                    folder.fetch(key)
                with self.assertRaises(sources.Skip):
                    folder.thumb(key)
        self.assertEqual(folder.fetch("sample-1.jpg")[1], "sample-1.jpg")

    def test_symlinks(self):
        """A link that stays inside the folder works; one that points out of it is neither listed nor opened."""
        fakes.pictures(os.path.join(self.data, "elsewhere"), n=1)
        os.symlink(os.path.join(self.data, "elsewhere", "sample-1.jpg"), os.path.join(self.pictures, "out.jpg"))
        os.symlink(os.path.join(self.data, "elsewhere"), os.path.join(self.pictures, "outdir"))
        os.makedirs(os.path.join(self.pictures, "sub"))
        os.symlink(os.path.join(self.pictures, "sample-2.jpg"), os.path.join(self.pictures, "sub", "in.jpg"))
        folder = self.folder()
        self.assertEqual(folder.keys(), ["sample-1.jpg", "sample-2.jpg", "sample-3.jpg", "sub/in.jpg"])
        self.assertEqual(folder.fetch("sub/in.jpg")[1], "sub/in.jpg")
        for key in ("out.jpg", "outdir/sample-1.jpg"):
            with self.subTest(key=key):
                with self.assertRaises(sources.Skip):
                    folder.fetch(key)
                with self.assertRaises(sources.Skip):
                    folder.thumb(key)

    def test_a_link_out_listed_before_is_left_out(self):
        """A pool from before (state.json) with a link out: drawn once, Skip, never again; /thumb says 404."""
        fakes.pictures(os.path.join(self.data, "elsewhere"), n=1)
        os.symlink(os.path.join(self.data, "elsewhere", "sample-1.jpg"), os.path.join(self.pictures, "out.jpg"))
        rot = self.rotation()
        src = rot.by_name["My pictures"]
        rot.state["pools"]["My pictures"] = {"at": time.time(), "keys": ["out.jpg"], "wide": True}
        with self.assertRaises(sources.Skip):
            rot.thumb("My pictures:out.jpg")
        with mock.patch.object(src, "keys", lambda: ["out.jpg"]):
            self.assertIsNone(rot.pick())
        self.assertIn("My pictures:out.jpg", rot.state["bad"])

    def test_a_folder_named_like_a_picture(self):
        os.makedirs(os.path.join(self.pictures, "dir.jpg"))
        folder = self.folder()
        before = len(os.listdir("/proc/self/fd"))
        for _ in range(50):
            with self.assertRaises(sources.Skip):
                folder.thumb("dir.jpg")
            with self.assertRaises(sources.Skip):
                folder.fetch("dir.jpg")
        self.assertLessEqual(len(os.listdir("/proc/self/fd")), before + 2)

    def test_a_fifo_doesnt_block(self):
        fifo = os.path.join(self.pictures, "fifo.jpg")
        os.mkfifo(fifo)
        self.addCleanup(self.unblock, fifo)
        folder = self.folder()
        for name, call in (("fetch", folder.fetch), ("thumb", folder.thumb)):
            with self.subTest(call=name):
                got = []

                def run():
                    try:
                        call("fifo.jpg")
                    except Exception as e:
                        got.append(e)

                t = threading.Thread(target=run, daemon=True)
                t.start()
                t.join(3)
                self.assertFalse(t.is_alive(), "%s blocked on a FIFO" % name)
                self.assertIsInstance(got[0], sources.Skip)

    def test_the_rotation_goes_on_past_a_fifo(self):
        """The FIFO alone first, so it's surely drawn: left out at once, and the next change takes a picture."""
        for f in os.listdir(self.pictures):
            os.rename(os.path.join(self.pictures, f), os.path.join(self.data, f))
        fifo = os.path.join(self.pictures, "fifo.jpg")
        os.mkfifo(fifo)
        self.addCleanup(self.unblock, fifo)
        rot = self.rotation()
        got = []
        t = threading.Thread(target=lambda: got.append(rot.pick()), daemon=True)
        t.start()
        t.join(5)
        self.assertFalse(t.is_alive(), "the rotation blocked on a FIFO")
        self.assertIsNone(got[0])
        self.assertIn("My pictures:fifo.jpg", rot.state["bad"])
        os.rename(os.path.join(self.data, "sample-1.jpg"), os.path.join(self.pictures, "sample-1.jpg"))
        self.assertEqual(rot.pick()[2], "My pictures:sample-1.jpg")

    @staticmethod
    def unblock(fifo):
        """Old code waits for a writer: one opened and closed lets it go."""
        try:
            os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))
        except OSError:
            pass


if __name__ == "__main__":
    unittest.main()
