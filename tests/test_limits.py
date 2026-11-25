"""AUG-1773: a picture is opened only in the formats the sources use and up to a number of pixels, checked before it's
decoded; the sources' work has its own threads, so the schedule never waits behind a slow one; keys have a length
limit and the pools of sources no longer in the options are forgotten; a title's tags are stripped in linear time."""
import asyncio
import concurrent.futures
import gc
import http.server
import io
import json
import os
import struct
import threading
import time
import unittest
import zlib
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer
from PIL import Image, ImageFile

import fakes
from frameart import api, image, limits, made, net, service, sources
from frameart import tv as tvmod
from frameart.service import Rotation
from test_smoke import Temp

KEY = {"Authorization": "Bearer " + fakes.FAKE_KEY}


def saved(fmt, size=(64, 36), mode="RGB"):
    out = io.BytesIO()
    Image.new(mode, size, 128).save(out, fmt)
    return out.getvalue()


def png_header(width, height):
    """A PNG that says it's width x height, with one small (broken) IDAT: only its header can be read."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\0" * 64)) + chunk(b"IEND", b""))


EPS = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 64 36\n%%EndComments\nshowpage\n%%EOF\n"


class RotationOnly(Temp):
    """The morning picture and tonight's show off, so a change takes a picture from the rotation at any time of day: in the
    morning window it would make the morning picture and put it on a TV that isn't here."""

    def rotation(self, **more):
        return super().rotation(**dict({"morning": False, "tonight": False}, **more))


class OpenImageTest(unittest.TestCase):
    def test_the_sources_formats_open(self):
        for fmt in ("JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF"):
            with self.subTest(fmt=fmt):
                img = image.open_image(saved(fmt))
                self.assertEqual((img.size, img.mode), ((64, 36), "RGB"))

    def test_other_formats_are_refused_before_they_are_decoded(self):
        others = {fmt: saved(fmt) for fmt in ("PCX", "PPM", "TGA", "SGI", "IM")}
        others["EPS"] = EPS
        loads = []
        with mock.patch.object(ImageFile.ImageFile, "load", lambda self: loads.append(self.format)):
            for fmt, data in others.items():
                with self.subTest(fmt=fmt):
                    with self.assertRaises(Exception):
                        image.open_image(data)
        self.assertEqual(loads, [])

    def test_too_many_pixels_are_refused_from_the_header(self):
        loads = []
        with mock.patch.object(ImageFile.ImageFile, "load", lambda self: loads.append(self.size)):
            # just over the limit (only a warning in Pillow's default), and a bomb far over it
            for size in ((12000, 7600), (40000, 40000)):
                with self.subTest(size=size):
                    with self.assertRaises(Exception):
                        image.open_image(png_header(*size))
        self.assertEqual(loads, [])

    def test_a_museums_original_opens(self):
        w, h = 8000, 6000  # 48 MP, from its header only
        self.assertLessEqual(w * h, image.MAX_PIXELS)
        with mock.patch.object(ImageFile.ImageFile, "load", lambda self: None):  # the data is only a stand-in
            self.assertEqual(image.open_image(png_header(w, h)).size, (w, h))

    def test_draft_still_makes_a_thumbnail_small(self):
        img = image.open_image(saved("JPEG", (3840, 2160)), draft=image.THUMB)
        self.assertLess(img.width, 3840)
        self.assertGreaterEqual(img.width, image.THUMB)

    def test_a_broken_picture_raises_in_open_image(self):
        with self.assertRaises(Exception):
            image.open_image(saved("JPEG", (640, 360))[:400])

    def test_sideways_photo_is_turned(self):
        img = Image.new("RGB", (36, 64), 50)
        exif = img.getexif()
        exif[0x0112] = 6  # turned 90°
        out = io.BytesIO()
        img.save(out, "JPEG", exif=exif)
        self.assertEqual(image.open_image(out.getvalue()).size, (64, 36))


class MadeTest(unittest.TestCase):
    def test_logo_only_in_the_formats_and_size(self):
        stasera = mock.Mock(image=lambda path: "http://127.0.0.1:1" + path)
        for data in (saved("PCX"), EPS, png_header(40000, 40000)):
            with mock.patch.object(net, "get", return_value=data):
                self.assertIsNone(made._logo(stasera, "/logo"))
        with mock.patch.object(net, "get", return_value=saved("PNG", (200, 80), "RGBA")):
            self.assertEqual(made._logo(stasera, "/logo").size, (200, 80))


class FolderTest(Temp):
    def test_a_bomb_or_another_format_is_skipped(self):
        folder = sources.Folder({"name": "My pictures", "query": self.pictures}, {})
        for name, data in (("bomb.png", png_header(40000, 40000)), ("over.png", png_header(12000, 7600)),
                           ("eps.tif", EPS), ("pcx.bmp", saved("PCX"))):
            with open(os.path.join(self.pictures, name), "wb") as f:
                f.write(data)
            with self.subTest(name=name):
                with self.assertRaises(sources.Skip):
                    folder.fetch(name)

    def test_a_file_over_the_byte_cap_is_skipped_unread(self):
        folder = sources.Folder({"name": "My pictures", "query": self.pictures}, {})
        with open(os.path.join(self.pictures, "huge.jpg"), "wb") as f:
            f.truncate(net.LIMIT + 1)  # sparse: nothing written
        with self.assertRaises(sources.Skip):
            folder.read("huge.jpg")


class ThreadsTest(RotationOnly, unittest.IsolatedAsyncioTestCase):
    """asyncio's default pool is the schedule's (guard, the TV, Home Assistant): the sources work in their own."""

    async def settled(self, rot):
        """The background listings done, before the data folder goes."""
        for _ in range(100):
            if not rot.reading:
                return
            await asyncio.sleep(0.05)

    def rotation_of(self, n):
        entries = []
        for i in range(n):
            folder = fakes.pictures(os.path.join(self.data, "folder%d" % i), n=1)
            entries.append({"category": "Category %d" % i, "name": "Source %d" % i, "type": "folder",
                            "query": folder})
        rot = self.rotation(sources=entries)
        save, lock = rot.state.save, threading.Lock()

        def one_at_a_time():  # listings in parallel each save state.json: one at a time here
            with lock:
                save()
        rot.state.save = one_at_a_time
        return rot

    async def test_the_schedule_goes_on_while_the_sources_are_stuck(self):
        loop = asyncio.get_running_loop()
        default = concurrent.futures.ThreadPoolExecutor(2, "default")
        loop.set_default_executor(default)
        rot = self.rotation_of(4)
        release = threading.Event()
        self.addCleanup(release.set)

        def stuck(src):
            release.wait(20)
            return []

        with mock.patch.object(sources.Folder, "keys", stuck):
            change = asyncio.create_task(rot.change())
            for c in rot.categories:
                await rot.gallery(c)  # each lists its unlisted source in the background
            await asyncio.sleep(0.3)
            started = time.monotonic()
            try:
                await asyncio.wait_for(rot._guard(), 3)
            except asyncio.TimeoutError:
                pass
            took = time.monotonic() - started
            release.set()
            await change
            await self.settled(rot)
        self.assertLess(took, 3, "the schedule waited for the sources")

    async def test_downloads_are_not_in_the_default_pool(self):
        loop = asyncio.get_running_loop()
        loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(4, "default"))
        rot = self.rotation()
        rot.pool(rot.by_name["My pictures"])
        threads = {}

        def where(name, f):
            def run(*args):
                threads[name] = threading.current_thread().name
                return f(*args)
            return run

        render, prepared, thumb, read = rot.render, rot.prepared, rot.thumb, rot._read
        with mock.patch.object(rot, "render", where("render", render)), \
                mock.patch.object(rot, "prepared", where("prepared", lambda what=None: None)), \
                mock.patch.object(rot, "thumb", where("thumb", thumb)), \
                mock.patch.object(rot, "_read", where("_read", read)):
            await rot.change()
            with self.assertRaises(Exception):  # no TV here: up to the render, then it fails
                await rot.choose("My pictures:sample-1.jpg")
            client = TestClient(TestServer(api.app(rot)))
            await client.start_server()
            try:
                r = await client.get("/thumb", params={"key": "My pictures:sample-1.jpg"}, headers=KEY)
                self.assertEqual(r.status, 200)
            finally:
                await client.close()
            del rot.state["pools"]["My pictures"]
            await rot.gallery("My pictures")
            await self.settled(rot)
        self.assertEqual(set(threads), {"render", "prepared", "thumb", "_read"})
        for name, thread in threads.items():
            with self.subTest(name=name):
                self.assertFalse(thread.startswith("default"), thread)


def service_rotation(test, ids):
    svc = {"name": "museum", "url": "http://127.0.0.1:1/search?q={query}", "items": "items", "id": "id",
           "image": "http://127.0.0.1:1/{id}.jpg"}
    rot = test.rotation(services=[svc], sources=[{"name": "Museum", "type": "museum", "query": "x"}])
    with mock.patch.object(sources.net, "get_json", return_value={"items": [{"id": i} for i in ids]}):
        keys = rot.pool(rot.by_name["Museum"])
    return rot, keys


class KeysTest(Temp):
    def test_long_keys_are_left_out_of_a_listing(self):
        long = "x" * (service.KEY_MAX + 1)
        rot, keys = service_rotation(self, ["a1", long, "b2", "c" * service.KEY_MAX])
        self.assertEqual(keys, ["a1", "b2", "c" * service.KEY_MAX])
        self.assertEqual(rot.state["pools"]["Museum"]["keys"], keys)

    def test_a_pool_has_a_cap(self):
        with mock.patch.object(service, "POOL_MAX", 3):
            rot, keys = service_rotation(self, ["k%d" % i for i in range(10)])
        self.assertEqual(len(keys), 3)

    def test_old_state_loads_and_loses_only_what_isnt_used(self):
        long = "y" * (service.KEY_MAX + 50)
        kept = {
            "bad": ["Gone:a", "My pictures:" + long, "My pictures:z.jpg"],
            "never": ["Gone:a", "My pictures:z.jpg"],
            "unfit": ["My pictures:" + long],
            "recent": ["Gone:b", "My pictures:sample-1.jpg"],
            "history": [{"key": "Gone:b", "label": "Gone: b", "at": 1}],
            "shown_at": {"Gone:b": 1, "My pictures:sample-1.jpg": 2},
            "uploaded": [{"key": "Gone:b", "content_id": "MY_F0001"}],
        }
        state = dict(kept, pools={
            "Gone": {"at": 1, "keys": ["a", "b"], "wide": True},
            "My pictures": {"at": 2, "keys": ["sample-1.jpg", long, "sample-2.jpg"], "wide": True},
            "Broken": "not a pool"})
        with open(os.path.join(self.data, "state.json"), "w") as f:
            json.dump(state, f)
        settings = {"sources_off": [], "mode": "shuffle",
                    "fixed": {"key": "Gone:b", "label": "Gone: b", "until": time.time() + 3600}}
        with open(os.path.join(self.data, "settings.json"), "w") as f:
            json.dump(settings, f)

        rot = self.rotation()
        rot.state.save()
        with open(os.path.join(self.data, "state.json")) as f:
            after = json.load(f)
        self.assertEqual(after["pools"], {"My pictures": {"at": 2, "keys": ["sample-1.jpg", "sample-2.jpg"],
                                                          "wide": True}})
        for k, v in kept.items():
            self.assertEqual(after[k], v, k)
        with open(os.path.join(self.data, "settings.json")) as f:
            self.assertEqual(json.load(f), settings)
        self.assertEqual(rot.pick()[2].split(":")[0], "My pictures")


class TextTest(unittest.TestCase):
    def test_many_lt_signs_take_linear_time(self):
        started = time.monotonic()
        self.assertEqual(sources._text("<" * 100000), "")
        self.assertEqual(sources._text("<" * 100000, 10 ** 6), "<" * 100000)
        self.assertLess(time.monotonic() - started, 1)

    def test_titles_as_before(self):
        for raw, text in (
                ('<span class="fn">Mona Lisa</span>, <a href="x">Leonardo</a> (1503)', "Mona Lisa , Leonardo (1503)"),
                ("The Starry Night", "The Starry Night"),
                ("  Sunflowers\n<br/>  Vincent   van Gogh ", "Sunflowers Vincent van Gogh"),
                ('Woman with a Parasol label QS:Len,"Woman"', "Woman with a Parasol"),
                ("<i>Water Lilies</i> &amp; more", "Water Lilies &amp; more"),
                ("a" * 81, ""),
                ("<b>" + "b" * 80 + "</b>", "b" * 80)):
            with self.subTest(raw=raw):
                self.assertEqual(sources._text(raw), text)

class Garbage(Temp):
    def test_a_broken_pool_in_state_doesnt_stop_the_start(self):
        pools = {"My pictures": {"keys": 5, "at": "yesterday", "wide": True}}
        for name, p in (("A", {"keys": True}), ("B", {"keys": 1.5, "at": None}), ("C", {"keys": "abc"}),
                        ("D", [1]), ("E", None), ("F", {"keys": [1, None, "ok"], "at": [], "wide": True})):
            pools[name] = p
        with open(os.path.join(self.data, "state.json"), "w") as f:
            json.dump({"pools": pools}, f)
        sources_ = [{"category": "My pictures", "name": n, "type": "folder", "query": self.pictures}
                    for n in ("My pictures", "A", "B", "C", "D", "E", "F")]
        rot = self.rotation(sources=sources_)
        for name, p in rot.state["pools"].items():
            with self.subTest(name=name):
                self.assertIsInstance(p["keys"], list)
                self.assertIsInstance(p["at"], (int, float))
        self.assertEqual(rot.state["pools"]["C"]["keys"], [])
        self.assertEqual(rot.state["pools"]["F"]["keys"], ["ok"])
        self.assertTrue(rot.pick())
        rot.status()


class Answers(http.server.ThreadingHTTPServer):
    """A service at 127.0.0.1: /list/* lists two pictures; /img/* answers as `how` says: "429" (Retry-After: 1),
    "drip" (headers a byte at a time, never done); /once/* answers 429 the first time, then the list."""

    def __init__(self, how):
        server = self
        self.asked = 0

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                server.asked += 1
                if self.path.startswith("/list/") or (self.path.startswith("/once/") and server.asked > 1):
                    body = json.dumps({"items": [{"id": "a"}, {"id": "b"}]}).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif how == "drip" and self.path.startswith("/img/"):
                    try:
                        self.wfile.write(b"HTTP/1.1 200 OK\r\n")
                        for _ in range(600):
                            self.wfile.write(b"X")
                            self.wfile.flush()
                            time.sleep(0.05)
                    except OSError:
                        pass
                else:
                    self.send_response(429)
                    self.send_header("Retry-After", "1")
                    self.send_header("Content-Length", "0")
                    self.end_headers()

            def log_message(self, *a):
                pass

        super().__init__(("127.0.0.1", 0), Handler)
        self.daemon_threads = True
        self.port = self.server_address[1]
        threading.Thread(target=self.serve_forever, daemon=True).start()


class ChangeDeadlineTest(RotationOnly, unittest.IsolatedAsyncioTestCase):
    def rotation_for(self, how, path="list"):
        server = Answers(how)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        svc = {"name": "svc", "url": "http://127.0.0.1:%d/%s/{query}" % (server.port, path), "items": "items",
               "id": "id", "image": "http://127.0.0.1:%d/img/{id}" % server.port}
        return self.rotation(services=[svc], sources=[{"name": "Slow", "type": "svc", "query": "q"}])

    async def change_takes(self, rot):
        started = time.monotonic()
        with mock.patch.object(service, "CHANGE_SECONDS", 2, create=True):
            try:
                await asyncio.wait_for(rot.change(), 12)
            except asyncio.TimeoutError:
                pass
        return time.monotonic() - started

    async def test_a_source_that_answers_429_doesnt_hold_a_change(self):
        rot = self.rotation_for("429")
        took = await self.change_takes(rot)
        self.assertLess(took, 4)
        self.assertFalse(rot.making.locked())
        self.assertIn("slow", rot.nothing)

    async def test_a_source_that_drips_doesnt_hold_a_change(self):
        rot = self.rotation_for("drip")
        took = await self.change_takes(rot)
        self.assertLess(took, 4)
        self.assertFalse(rot.making.locked())

    def test_a_listing_still_waits_for_retry_after(self):
        rot = self.rotation_for("429", "once")
        self.assertEqual(rot.pool(rot.by_name["Slow"]), ["a", "b"])


def hold_the_big_slot(test):
    """Another thread's job holds the big slot until the Event is set (or the test ends)."""
    holding, done = threading.Event(), threading.Event()
    test.addCleanup(done.set)

    def other():
        with limits.job():
            limits.hold(limits.SMALL + 1)
            holding.set()
            done.wait(20)
    threading.Thread(target=other, daemon=True).start()
    holding.wait(5)
    return done


class Round3Test(Temp):
    def setUp(self):
        super().setUp()
        for name, size in (("square-1.png", (1200, 1200)), ("square-2.png", (1100, 1100)),
                           ("wide.png", (1920, 1080))):
            Image.new("RGB", size, 90).save(os.path.join(self.pictures, name))
        for n in range(1, 4):  # only big pictures in the folder
            os.remove(os.path.join(self.pictures, "sample-%d.jpg" % n))
        small = mock.patch.object(limits, "SMALL", 2 ** 20)  # each of these is big
        small.start()
        self.addCleanup(small.stop)

    def test_a_refused_thumbnail_gives_its_memory_back_at_once(self):
        gc.disable()  # what a reference cycle keeps, the collector doesn't free here
        self.addCleanup(gc.enable)
        rot = self.rotation()
        rot.pool(rot.by_name["My pictures"])
        kept = []
        for name in ("square-1.png", "square-2.png"):  # not 16:9: refused, the exception (and its frames) kept
            try:
                rot.thumb("My pictures:" + name)
            except sources.Skip as e:
                kept.append(e)
        self.assertEqual(len(kept), 2)
        frame = kept[0].__traceback__
        while frame.tb_next:
            frame = frame.tb_next
        img = frame.tb_frame.f_locals["img"]
        with self.assertRaises(ValueError):  # its pixels are gone, though the image is still referred to
            img.getpixel((0, 0))
        with mock.patch.object(limits, "WAIT", 0.5):
            self.assertTrue(rot.thumb("My pictures:wide.png"))

    def test_busy_ends_the_pick(self):
        rot = self.rotation()
        rot.pool(rot.by_name["My pictures"])
        with mock.patch.object(limits, "WAIT", 0.5):
            other = hold_the_big_slot(self)
            started = time.monotonic()
            self.assertIsNone(rot.pick())
            took = time.monotonic() - started
            other.set()
        self.assertLess(took, 1.5)  # one wait, not one per try
        self.assertIn("memory", rot.nothing)
        self.assertEqual(rot.state["unfit"], [])

    def test_the_wait_for_memory_is_within_the_change(self):
        rot = self.rotation()
        rot.pool(rot.by_name["My pictures"])
        hold_the_big_slot(self)
        started = time.monotonic()
        self.assertIsNone(limits.within(0.5, rot.pick))  # WAIT is 60 s
        self.assertLess(time.monotonic() - started, 2)

    def test_raw_bytes_count(self):
        body = b"x" * (3 * 2 ** 20)
        server = Answers("429")
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with open(os.path.join(self.pictures, "raw.jpg"), "wb") as f:
            f.write(body)
        folder = sources.Folder({"name": "My pictures", "query": self.pictures}, {})
        url = "http://127.0.0.1:%d/list/x" % server.port
        listing = net.get(url)  # outside a job: no limit
        with mock.patch.object(limits, "SMALL", len(listing) // 2), mock.patch.object(limits, "WAIT", 0.3):
            hold_the_big_slot(self)
            with limits.job(), self.assertRaises(limits.Busy):
                net.get(url)  # a download bigger than SMALL needs the big slot
            with mock.patch.object(limits, "SMALL", 2 ** 20), limits.job(), self.assertRaises(limits.Busy):
                folder.read("raw.jpg")

class Routes(http.server.ThreadingHTTPServer):
    """127.0.0.1: path -> (status, headers, body)."""

    def __init__(self, routes):
        server = self
        self.routes = routes

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                status, headers, body = server.routes[self.path.split("?")[0]]
                self.send_response(status)
                for k, v in dict(headers, **{"Content-Length": str(len(body))}).items():
                    self.send_header(k, v)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

            def log_message(self, *a):
                pass

        super().__init__(("127.0.0.1", 0), Handler)
        self.daemon_threads = True
        self.port = self.server_address[1]
        threading.Thread(target=self.serve_forever, daemon=True).start()


def routes(test, table):
    server = Routes(table)
    test.addCleanup(server.server_close)
    test.addCleanup(server.shutdown)
    return "http://127.0.0.1:%d" % server.port


def jpeg(size):
    """A noisy JPEG: a file of some size, as a photo's."""
    out = io.BytesIO()
    Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3)).save(out, "JPEG", quality=95)
    return out.getvalue()


class Round4Test(Temp):
    def test_json_has_a_small_cap(self):
        base = routes(self, {"/big": (200, {}, b"[" + b"{}," * (2 * 2 ** 20) + b"{}]")})  # 6 MB
        with self.assertRaises(net.Refused):
            net.get_json(base + "/big")

    def test_parsed_json_counts_in_memory(self):
        base = routes(self, {"/list": (200, {}, b"[" + b"{}," * 400000 + b"{}]")})  # 1.2 MB, ~37 MB parsed
        with mock.patch.object(limits, "SMALL", 8 * 2 ** 20), mock.patch.object(limits, "WAIT", 0.3):
            hold_the_big_slot(self)
            with self.assertRaises(limits.Busy):
                net.get_json(base + "/list")

    def test_a_listing_keeps_only_what_it_uses(self):
        page = {"items": [{"id": "a", "image": "http://127.0.0.1:1/a.jpg", "title": "A", "pad": "x" * 2 ** 20,
                           "info": {"w": 1}}]}
        base = routes(self, {"/list/q": (200, {}, json.dumps(page).encode())})
        svc = {"name": "svc", "url": base + "/list/{query}", "items": "items", "id": "id", "image": "{image}",
               "title": "{title} {info.w}"}
        rot = self.rotation(services=[svc], sources=[{"name": "Web", "type": "svc", "query": "q"}])
        src = rot.by_name["Web"]
        self.assertEqual(rot.pool(src), ["a"])
        self.assertLess(len(json.dumps(src.items)), 10000)
        context = src.context("a", False)
        self.assertEqual((context["image"], context["title"], context["info"]), ("http://127.0.0.1:1/a.jpg", "A",
                                                                                {"w": 1}))

    def test_a_listing_keeps_no_more_items_than_the_pool(self):
        page = {"items": [{"id": "k%d" % i} for i in range(10)]}
        base = routes(self, {"/list/q": (200, {}, json.dumps(page).encode())})
        svc = {"name": "svc", "url": base + "/list/{query}?page={page}", "items": "items", "id": "id",
               "image": base + "/img/{id}", "pages": 20}
        rot = self.rotation(services=[svc], sources=[{"name": "Web", "type": "svc", "query": "q"}])
        src = rot.by_name["Web"]
        with mock.patch.object(sources, "POOL_MAX", 3, create=True):
            self.assertEqual(len(rot.pool(src)), 3)
        self.assertEqual(len(src.items), 3)

    def test_a_listing_keeps_no_long_keys_and_little_text(self):
        long = "\U0001F600" * (service.KEY_MAX + 1)
        page = {"items": [{"id": long}] + [{"id": "k%d" % i, "title": "t" * 100} for i in range(50)]}
        base = routes(self, {"/list/q": (200, {}, json.dumps(page).encode())})
        svc = {"name": "svc", "url": base + "/list/{query}?page={page}", "items": "items", "id": "id",
               "image": base + "/img/{id}", "title": "{title}", "pages": 20}
        rot = self.rotation(services=[svc], sources=[{"name": "Web", "type": "svc", "query": "q"}])
        src = rot.by_name["Web"]
        with mock.patch.object(sources, "ITEMS_TEXT", 2000, create=True):
            src.keys()
            first = len(json.dumps(src.items))
            self.assertFalse(long in src.items, "a key longer than KEY_MAX is kept")
            self.assertLess(first, 2000 + 600)  # stops storing (and paging) past ITEMS_TEXT
            src.keys()  # listed again: what's kept is replaced, not added to
            self.assertEqual(len(json.dumps(src.items)), first)

    def test_a_large_web_original_isnt_counted_twice(self):
        raw = jpeg((3000, 1688))  # 20 MB decoded
        base = routes(self, {"/list/q": (200, {}, json.dumps({"items": [{"id": "a"}]}).encode()),
                             "/img/a": (200, {}, raw)})
        svc = {"name": "svc", "url": base + "/list/{query}", "items": "items", "id": "id", "image": base + "/img/{id}"}
        rot = self.rotation(services=[svc], sources=[{"name": "Web", "type": "svc", "query": "q"}])
        rot.pool(rot.by_name["Web"])
        decoded = 3000 * 1688 * 4
        with mock.patch.object(limits, "MEMORY", decoded + len(raw) + len(raw) // 2):  # room for it counted once
            self.assertTrue(rot.render(rot.by_name["Web"], "a"))
        with mock.patch.object(limits, "MEMORY", decoded // 2):  # too big for memory: skipped, not unfit
            self.assertIsNone(rot.pick())
        self.assertEqual(rot.state["unfit"], [])

    def test_a_big_download_needs_the_slot_before_small_is_full(self):
        base = routes(self, {"/img": (200, {}, b"x" * (2 * 2 ** 20))})
        with mock.patch.object(limits, "RAW_SMALL", 2 ** 20, create=True), mock.patch.object(limits, "WAIT", 0.3):
            hold_the_big_slot(self)
            with limits.job(), self.assertRaises(limits.Busy):  # 2 MB of SMALL's 64 MB, but past RAW_SMALL
                net.get(base + "/img")

    def test_a_4k_thumbnail_doesnt_wait_for_the_big_slot(self):
        Image.new("RGB", (3840, 2160), 80).save(os.path.join(self.pictures, "4k.png"))
        rot = self.rotation()
        rot.pool(rot.by_name["My pictures"])
        with mock.patch.object(limits, "WAIT", 0.5):
            hold_the_big_slot(self)
            self.assertTrue(rot.thumb("My pictures:4k.png"))

    def test_nothing_is_cleared_by_a_picture(self):
        rot = self.rotation()
        rot.nothing = "no memory free for a big picture now"
        self.assertTrue(rot.pick())
        self.assertEqual(rot.nothing, "")


class ThumbDeadlineTest(Temp, unittest.IsolatedAsyncioTestCase):
    async def test_a_thumbnail_doesnt_wait_for_retry_after(self):
        base = routes(self, {"/list/q": (200, {}, json.dumps({"items": [{"id": "a"}]}).encode()),
                             "/thumb/a": (503, {"Retry-After": "120"}, b"x" * 1000)})
        svc = {"name": "svc", "url": base + "/list/{query}", "items": "items", "id": "id",
               "image": base + "/img/{id}", "thumb": base + "/thumb/{id}"}
        rot = self.rotation(services=[svc], sources=[{"name": "Web", "type": "svc", "query": "q"}])
        rot.pool(rot.by_name["Web"])
        client = TestClient(TestServer(api.app(rot)))
        await client.start_server()
        started = time.monotonic()
        try:
            r = await asyncio.wait_for(client.get("/thumb", params={"key": "Web:a"}, headers=KEY), 20)
            self.assertEqual(r.status, 502)
        except asyncio.TimeoutError:
            pass
        finally:
            await client.close()
        self.assertLess(time.monotonic() - started, 5)


class MemoryTest(Temp):
    def test_big_decodes_wait_for_each_other(self):
        data = saved("PNG", (1000, 1000))  # 4 MB decoded: big, with SMALL at 1 MB
        with mock.patch.object(limits, "SMALL", 2 ** 20), mock.patch.object(limits, "WAIT", 0.3):
            other = hold_the_big_slot(self)
            started = time.monotonic()
            with limits.job(), self.assertRaises(limits.Busy):
                image.open_image(data)
            self.assertGreaterEqual(time.monotonic() - started, 0.3)
            with limits.job():
                self.assertEqual(image.open_image(saved("PNG", (300, 300))).size, (300, 300))  # small: no wait
            other.set()
            with limits.job():
                self.assertEqual(image.open_image(data).size, (1000, 1000))

    def test_sideways_pictures_near_the_budget_dont_stall(self):
        img = Image.new("RGB", (1125, 2000), 70)
        exif = img.getexif()
        exif[0x0112] = 6
        out = io.BytesIO()
        img.save(out, "JPEG", exif=exif)
        data = out.getvalue()
        load = ImageFile.ImageFile.load

        def slow_load(self):  # each decode takes a moment, so they overlap
            time.sleep(0.3)
            return load(self)
        decoded = 1125 * 2000 * 4
        with mock.patch.object(limits, "MEMORY", int(decoded * 2.5)), mock.patch.object(limits, "WAIT", 5), \
                mock.patch.object(limits, "SMALL", 2 ** 20), mock.patch.object(ImageFile.ImageFile, "load", slow_load):
            def one(_):
                with limits.job():
                    return image.open_image(data).size
            with concurrent.futures.ThreadPoolExecutor(4) as threads:
                sizes = list(threads.map(one, range(4)))
        self.assertEqual(sizes, [(2000, 1125)] * 4)

    def test_more_memory_than_there_is_is_refused(self):
        with mock.patch.object(limits, "MEMORY", 5 * 10 ** 6):
            self.assertEqual(image.open_image(saved("PNG", (1000, 1000))).size, (1000, 1000))
            for mode in ("F", "I;16", "RGBA"):  # decoded, then converted to RGB: more than 5 MB, skipped for now
                with self.subTest(mode=mode):
                    with self.assertRaises(limits.TooBig):
                        image.open_image(saved("TIFF" if mode != "RGBA" else "PNG", (1000, 1000), mode))

    def test_a_thumbnail_is_made_in_place(self):
        img = image.open_image(saved("PNG", (1920, 1080)))
        with mock.patch.object(Image.Image, "copy", side_effect=AssertionError("a copy")):
            image.thumbnail(img)
        self.assertEqual(max(img.size), image.THUMB)

    def test_busy_isnt_unfit(self):
        folder = sources.Folder({"name": "My pictures", "query": self.pictures}, {})
        with mock.patch.object(limits, "SMALL", 2 ** 10), mock.patch.object(limits, "WAIT", 0.2):
            hold_the_big_slot(self)
            with limits.job(), self.assertRaises(limits.Busy):
                folder.fetch("sample-1.jpg")

    def test_memory_freed_in_any_thread_goes_back(self):
        def rss():
            with open("/proc/self/status") as f:
                return next(int(line.split()[1]) // 1024 for line in f if line.startswith("VmRSS"))
        data = saved("PNG", (5000, 3000))  # 60 MB decoded

        def one(_):
            with limits.job():
                image.thumbnail(image.open_image(data))
        before = rss()
        with concurrent.futures.ThreadPoolExecutor(6) as threads:
            for _ in range(3):  # the threads stay, as the sources' do
                list(threads.map(one, range(6)))
            self.assertLess(rss() - before, 120)

    def test_a_bomb_in_the_folder_is_unfit_for_a_thumbnail(self):
        with open(os.path.join(self.pictures, "bomb.png"), "wb") as f:
            f.write(png_header(40000, 40000))
        rot = self.rotation()
        rot.pool(rot.by_name["My pictures"])
        with self.assertRaises(sources.Skip):
            rot.thumb("My pictures:bomb.png")
        self.assertIn("My pictures:bomb.png", rot.state["unfit"])


class ScheduleThreadsTest(Temp, unittest.IsolatedAsyncioTestCase):
    async def test_the_schedule_ticks_while_the_tv_tab_and_stasera_are_slow(self):
        asyncio.get_running_loop().set_default_executor(concurrent.futures.ThreadPoolExecutor(2, "default"))
        rot = self.rotation()
        release = threading.Event()
        self.addCleanup(release.set)

        def slow(*args, **kw):
            release.wait(20)
            raise OSError("slow")

        ticks, looks = [], []
        guard = rot._guard

        async def counted():
            ticks.append(time.monotonic())
            await guard()

        with mock.patch.object(tvmod, "device", return_value={"device": {"PowerState": "on"}}), \
                mock.patch.object(tvmod, "app_state", slow), mock.patch.object(tvmod, "volume", slow), \
                mock.patch.object(rot.stasera, "_request", slow), \
                mock.patch.object(tvmod, "powered_on", lambda *a: looks.append(1) or True), \
                mock.patch.object(service, "GUARD_LOOK", 0.1), mock.patch.object(service, "POWER_LOOK", 0.1), \
                mock.patch.object(rot, "_guard", counted), mock.patch.object(rot, "_tv_timer", mock.AsyncMock()):
            tab = asyncio.create_task(rot.tv_info(fresh=True))  # 14 of the TV's apps asked at once
            link = asyncio.create_task(rot.stasera.link())
            await asyncio.sleep(0.3)
            schedule = asyncio.create_task(rot.guard())
            power = asyncio.create_task(rot.watch_power())
            await asyncio.sleep(1.5)
            counted_ticks, counted_looks = len(ticks), len(looks)
            schedule.cancel()
            power.cancel()
            release.set()
            await asyncio.gather(tab, link, schedule, power, return_exceptions=True)
        self.assertGreater(counted_ticks, 5)
        self.assertGreater(counted_looks, 5)


if __name__ == "__main__":
    unittest.main()
