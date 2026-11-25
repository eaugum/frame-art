"""AUG-1777: an emptied api_key gives a new key, and the API's key never becomes a picture in the log or the events."""
import asyncio
import json
import logging
import os
import time
import unittest
import urllib.parse
from unittest import mock
from urllib.parse import urlsplit

from aiohttp.test_utils import TestClient, TestServer

import fakes
from frameart import api, events
from test_smoke import Temp

KEY = {"Authorization": "Bearer " + fakes.FAKE_KEY}
OLD_KEY = "FAKE-OLD-KEY-0000000000000000000"  # a key an older version made and kept in api_key.txt
OWN_KEY = "FAKE-OWN-KEY-0001"


class Supervisor:
    """Stands in for the Supervisor's options call: what's posted is the next start's options.json."""

    def __init__(self, data, refuse=False):
        self.data, self.refuse, self.posts = data, refuse, 0

    def __call__(self, req, timeout=None):
        url = urlsplit(req.full_url)
        if (url.hostname, url.path) != ("supervisor", "/addons/self/options"):
            raise AssertionError("not the Supervisor's options call: %s" % url.path)
        if self.refuse:
            raise OSError("the Supervisor said no")
        self.posts += 1
        fakes.write_options(self.data, json.loads(req.data)["options"])
        return fakes.Response(b'{"result": "ok"}')


class Starts(Temp):
    """Starts of the add-on, each reading options.json as the Supervisor left it."""

    def setUp(self):
        super().setUp()
        os.environ["SUPERVISOR_TOKEN"] = "FAKE-SUPERVISOR-0000"
        self.supervisor = Supervisor(self.data)
        self.set_option("")

    def options(self):
        with open(os.path.join(self.data, "options.json")) as f:
            return json.load(f)

    def set_option(self, value):
        """What the owner types in the Configuration tab (and saves)."""
        fakes.write_options(self.data, fakes.options(self.pictures, api_key=value))

    def start(self):
        with mock.patch("urllib.request.urlopen", self.supervisor):
            return api.api_key(self.options(), self.data)

    def store(self, text, mode="w"):
        with open(os.path.join(self.data, "api_key.txt"), mode) as f:
            f.write(text)


class RotationTest(Starts):
    def test_first_start_makes_a_key_and_writes_it_into_the_options(self):
        key = self.start()
        self.assertGreaterEqual(len(key), 16)
        self.assertTrue(self.options()["api_key"] == key, "the key isn't in the options")
        self.assertTrue(self.start() == key, "a restart changed the key")

    def test_emptying_the_field_makes_a_new_key(self):
        first = self.start()
        self.set_option("")
        second = self.start()
        self.assertTrue(second and second != first, "the emptied field brought the old key back")
        self.assertTrue(self.options()["api_key"] == second, "the new key isn't in the options")

    def test_emptying_after_a_restart_makes_a_new_key(self):
        first = self.start()
        self.assertTrue(self.start() == first)
        self.set_option("")
        self.assertTrue(self.start() not in ("", first), "the emptied field brought the old key back")

    def test_emptying_an_own_key_makes_a_new_one(self):
        made = self.start()
        self.set_option(OWN_KEY)
        self.assertEqual(self.start(), OWN_KEY)
        self.set_option("")
        self.assertTrue(self.start() not in ("", made, OWN_KEY), "an old key came back")

    def test_upgrade_with_the_key_in_the_options(self):
        """An older version kept its key in api_key.txt and wrote it into the options: it stays, until emptied."""
        self.store(OLD_KEY)
        self.set_option(OLD_KEY)
        self.assertEqual(self.start(), OLD_KEY)
        self.set_option("")
        self.assertTrue(self.start() not in ("", OLD_KEY), "the old key came back")

    def test_upgrade_with_an_empty_option_keeps_the_stored_key_once(self):
        """The options never got the older version's key: it's kept (Frame TV has it) and written in; emptied after
        that, a new one comes."""
        self.store(OLD_KEY)
        self.assertEqual(self.start(), OLD_KEY)
        self.assertEqual(self.options()["api_key"], OLD_KEY)
        self.set_option("")
        self.assertTrue(self.start() not in ("", OLD_KEY), "the old key came back")

    def test_a_key_the_options_couldnt_take_stays(self):
        self.supervisor.refuse = True
        first = self.start()
        self.assertTrue(self.start() == first, "the key changed while the options couldn't be written")
        os.environ.pop("SUPERVISOR_TOKEN")
        self.assertTrue(self.start() == first, "the key changed without a Supervisor")

    def test_a_bad_stored_key_still_starts(self):
        for what, bad in (("empty", ""), ("blank", " \n"), ("not text", b"\xff\xfe\x00\x81"), ("too short", "abc"),
                          ("control characters", "\x00" * 32)):
            with self.subTest(what=what):
                self.set_option("")
                self.store(bad, "wb" if isinstance(bad, bytes) else "w")
                key = self.start()
                self.assertTrue(len(key) >= 16 and key.isprintable(), "no usable key")

    def test_a_folder_in_the_way_still_starts(self):
        os.makedirs(os.path.join(self.data, "api_key.txt"))
        self.supervisor.refuse = True
        key = self.start()
        self.assertGreaterEqual(len(key), 16)
        self.set_option(OWN_KEY)
        self.assertEqual(self.start(), OWN_KEY)


class OldKeyRefusedTest(Starts, unittest.IsolatedAsyncioTestCase):
    async def test_the_old_key_is_refused_after_emptying(self):
        first = self.start()
        self.set_option("")
        with mock.patch("urllib.request.urlopen", self.supervisor):
            client = TestClient(TestServer(api.app(self.rotation(api_key=""))))
        await client.start_server()
        try:
            old = await client.get("/status", headers={"Authorization": "Bearer " + first})
            new = await client.get("/status", headers={"Authorization": "Bearer " + self.options()["api_key"]})
        finally:
            await client.close()
        self.assertEqual(old.status, 401)
        self.assertEqual(new.status, 200)


class Api(Temp, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.rot = self.rotation()
        self.rot.pool(self.rot.by_name["My pictures"])
        self.rot._put = mock.AsyncMock()
        server = TestServer(api.app(self.rot))
        await server.start_server(access_log=None)  # as api.serve runs it
        self.client = TestClient(server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()


class PictureTest(Api):
    """/show and /thumb take the picture as ?picture=; ?key= is a picture only when the API's key came another way."""

    async def check(self, method, path, params, headers, status):
        r = await self.client.request(method, path, params=params, headers=headers)
        self.assertEqual(r.status, status, "%s %s %s" % (method, path, list(params)))
        return r

    async def test_picture(self):
        r = await self.check("GET", "/thumb", {"picture": "My pictures:sample-1.jpg"}, KEY, 200)
        self.assertTrue((await r.read()).startswith(b"\xff\xd8"))
        await self.check("POST", "/show", {"picture": "My pictures:sample-2.jpg"}, KEY, 200)
        self.assertEqual(self.rot.cfg["fixed"]["key"], "My pictures:sample-2.jpg")
        # the API's key in the query and the picture as ?picture=
        await self.check("POST", "/show", {"key": fakes.FAKE_KEY, "picture": "My pictures:sample-3.jpg"}, {}, 200)
        self.assertEqual(self.rot.cfg["fixed"]["key"], "My pictures:sample-3.jpg")
        await self.check("GET", "/thumb", {"key": fakes.FAKE_KEY, "picture": "My pictures:sample-3.jpg"}, {}, 200)

    async def test_older_callers_with_the_key_another_way(self):
        await self.check("GET", "/thumb", {"key": "My pictures:sample-1.jpg"}, KEY, 200)
        await self.check("POST", "/show", {"key": "My pictures:sample-1.jpg"}, KEY, 200)
        self.assertEqual(self.rot.cfg["fixed"]["key"], "My pictures:sample-1.jpg")
        with mock.patch.object(api, "INGRESS", "127.0.0.1"):  # the page before AUG-1777, through ingress
            await self.check("GET", "/thumb", {"key": "My pictures:sample-2.jpg"}, {}, 200)
            await self.check("POST", "/show", {"key": "My pictures:sample-2.jpg"}, {}, 200)
        self.assertEqual(self.rot.cfg["fixed"]["key"], "My pictures:sample-2.jpg")

    async def test_the_key_never_reaches_the_log_or_the_events(self):
        calls = [("POST", "/show", {"key": fakes.FAKE_KEY}, {}),
                 ("POST", "/show", [("key", fakes.FAKE_KEY), ("key", "My pictures:sample-1.jpg")], {}),
                 ("GET", "/thumb", {"key": fakes.FAKE_KEY}, {}),
                 ("POST", "/show", {"picture": fakes.FAKE_KEY}, KEY),
                 ("GET", "/thumb", {"picture": fakes.FAKE_KEY}, KEY),
                 ("POST", "/never", {"picture": fakes.FAKE_KEY}, KEY)]
        answers = []
        with self.assertLogs(level="DEBUG") as logged:
            logging.getLogger(__name__).debug("the calls")
            for method, path, params, headers in calls:
                r = await self.client.request(method, path, params=params, headers=headers)
                self.assertIn(r.status, (400, 404), "%s %s" % (method, path))
                answers.append(await r.text())
        self.assertIsNone(self.rot.cfg.get("fixed"), "a picture was chosen")
        self.assertEqual(self.rot._put.await_count, 0)
        try:
            with open(os.path.join(self.data, "events.jsonl"), encoding="utf-8") as f:
                stored = f.read()
        except FileNotFoundError:
            stored = ""
        shown = [await (await self.client.get(path, headers=KEY)).text() for path in ("/events", "/events/export")]
        for what, text in [("the log", "\n".join(logged.output)), ("events.jsonl", stored),
                           ("/events", shown[0]), ("/events/export", shown[1])] + \
                          [("the answer to %s %s" % c[:2], a) for c, a in zip(calls, answers)]:
            with self.subTest(where=what):
                self.assertTrue(fakes.FAKE_KEY not in text, "the API's key is in %s" % what)


class WarningTest(Starts):
    def test_the_warning_says_where_the_key_is(self):
        self.supervisor.refuse = True
        with self.assertLogs("frameart.api", level="WARNING") as logged:
            self.start()
        self.assertIn("kept in %s" % os.path.join(self.data, "api_key.txt"), "\n".join(logged.output))

    def test_the_warning_doesnt_claim_a_file_that_isnt_there(self):
        os.makedirs(os.path.join(self.data, "api_key.txt"))
        self.supervisor.refuse = True
        with self.assertLogs("frameart.api", level="WARNING") as logged:
            self.start()
        text = "\n".join(logged.output)
        self.assertNotIn("kept in", text)
        self.assertNotIn("it's in", text)
        self.assertIn("a new one at the next start", text)


class NowhereTest(Api):
    """The API's key in any form reaches neither the log nor the events (AUG-1777, after review)."""

    def assertNoKey(self, text, where):
        self.assertTrue(fakes.FAKE_KEY.lower() not in text.lower(), "the API's key is in %s" % where)

    def stored_events(self):
        try:
            with open(os.path.join(self.data, "events.jsonl"), encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    async def raw(self, request):
        """A request as bytes, past the client's checks; the answer's status line."""
        reader, writer = await asyncio.open_connection(self.client.host, self.client.port)
        writer.write(request)
        await writer.drain()
        line = await reader.readline()
        writer.close()
        return line

    async def test_malformed_requests(self):
        k = fakes.FAKE_KEY.encode()
        requests = [
            b"POST /show?key=" + k + b"&picture=H\xc3\xb8stkveld HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\n\r\n",
            b"POST /show?key=" + k.lower() + b"&picture=a b HTTP/1.1\r\nHost: x\r\n\r\n",
            b"POST /show?key=" + k + b"\tx HTTP/1.1\r\nHost: x\r\n\r\n",
            b"POST /show?key=" + k + b" HTTP/9.9\r\nHost: x\r\n\r\n",
            b"POST /show?key=" + k + b"&x=" + b"a" * 9000 + b" HTTP/1.1\r\nHost: x\r\n\r\n",
            b"POST /show HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer " + k + b"\x01\r\nContent-Length: 0\r\n\r\n",
            b"POST /show HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer " + k + b"\x7f\r\nContent-Length: 0\r\n\r\n",
            b"POST /show HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer " + k + b"a" * 9000 + b"\r\n\r\n"]
        with self.assertLogs(level="DEBUG") as logged:
            for request in requests:
                self.assertIn(b" 400 ", await self.raw(request))
            await asyncio.sleep(0.2)
        text = "\n".join(logged.output)
        self.assertIn("Error handling request", text)  # still seen, without the key
        self.assertNoKey(text, "the log")

    async def test_pictures_holding_the_key(self):
        values = [" %s\n" % fakes.FAKE_KEY, "\t" + fakes.FAKE_KEY, fakes.FAKE_KEY.lower(), fakes.FAKE_KEY + "X",
                  "x" + fakes.FAKE_KEY, "My pictures:" + fakes.FAKE_KEY]
        with self.assertLogs(level="DEBUG") as logged:
            logging.getLogger(__name__).debug("the calls")
            for v in values:
                for method, path, names in (("POST", "/show", ("picture", "key")), ("GET", "/thumb", ("picture", "key")),
                                            ("POST", "/never", ("picture",))):
                    for params in [{name: v} for name in names]:
                        r = await self.client.request(method, path, params=params, headers=KEY)
                        self.assertEqual(r.status, 400, "%s %s %r" % (method, path, list(params)))
        self.assertIsNone(self.rot.cfg.get("fixed"))
        self.assertEqual(self.stored_events(), "")
        self.assertNoKey("\n".join(logged.output), "the log")

    async def test_settings_event_has_the_checked_values(self):
        with self.assertLogs(level="DEBUG") as logged:
            r = await self.client.post("/settings", json={"morning_time": "07:05:00",
                                                          "categories_off": [fakes.FAKE_KEY]}, headers=KEY)
            self.assertEqual(r.status, 200)
            r = await self.client.post("/schedule", json={"interval_minutes": "45"}, headers=KEY)
            self.assertEqual(r.status, 200)
        stored = self.stored_events()
        self.assertIn("morning_time=07:05", stored)
        self.assertNotIn("07:05:00", stored)
        self.assertIn("interval_minutes=45", stored)
        export = await (await self.client.get("/events/export", headers=KEY)).text()
        for where, text in (("events.jsonl", stored), ("/events/export", export),
                            ("the log", "\n".join(logged.output))):
            with self.subTest(where=where):
                self.assertNoKey(text, where)


class StoredEventsTest(Temp, unittest.IsolatedAsyncioTestCase):
    """Events kept from before the update (AUG-1777) lose the key at the start."""

    async def test_old_events_are_cleaned_at_the_start(self):
        k = fakes.FAKE_KEY
        old = [{"id": int(time.time() * 1000) - 5000 + i, "at": time.time() - 5, "source": "api", "kind": kind,
                "detail": detail, "why": why}
               for i, (kind, detail, why) in enumerate([("show", k, "Frame TV (/show)"),
                                                        ("show", "My pictures:sample-1.jpg", "Frame TV (/show)"),
                                                        (k, "GET /x?key=other Bearer other", "Frame TV " + k.lower())])]
        path = os.path.join(self.data, "events.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(json.dumps(e) + "\n" for e in old)
        events.setup(self.data)  # the start, before the API
        client = TestClient(TestServer(api.app(self.rotation())))
        await client.start_server()
        try:
            shown = [await (await client.get(p, headers=KEY)).text() for p in ("/events?since=0", "/events/export")]
        finally:
            await client.close()
        with open(path, encoding="utf-8") as f:
            stored = f.read()
        for where, text in (("events.jsonl", stored), ("/events", shown[0]), ("/events/export", shown[1])):
            with self.subTest(where=where):
                self.assertTrue(k.lower() not in text.lower(), "the API's key is in %s" % where)
                self.assertNotIn("other", text)
                self.assertIn("My pictures:sample-1.jpg", text)
                self.assertEqual(len(json.loads(shown[1])), 3)

    async def test_untouched_when_clean(self):
        path = os.path.join(self.data, "events.jsonl")
        events.add("api", "show", "My pictures:sample-1.jpg")
        before = os.stat(path).st_mtime_ns
        api.app(self.rotation())
        self.assertEqual(os.stat(path).st_mtime_ns, before)


class AppEventTest(Api):
    async def test_kind_holding_the_key(self):
        r = await self.client.post("/event", json={"events": [{"kind": fakes.FAKE_KEY, "detail": "x"}]}, headers=KEY)
        self.assertEqual(r.status, 200)
        export = await (await self.client.get("/events/export", headers=KEY)).text()
        self.assertTrue(fakes.FAKE_KEY not in export, "the API's key is in the events")


class NonAsciiKeyTest(Temp, unittest.IsolatedAsyncioTestCase):
    """A key typed with letters outside ASCII is hidden in the forms aiohttp logs it in too."""
    OWN = "FAKE-H\u00f8st-n\u00f8kkel-0000"

    async def test_malformed_requests(self):
        server = TestServer(api.app(self.rotation(api_key=self.OWN)))
        await server.start_server()  # with aiohttp's access log too
        client = TestClient(server)
        await client.start_server()
        raw = self.OWN.encode()
        quoted = urllib.parse.quote(self.OWN, safe="").encode()
        requests = [b"POST /show?picture=" + raw + b"&x=a b HTTP/1.1\r\nHost: x\r\n\r\n",
                    b"POST /show?picture=" + quoted + b"&x=a b HTTP/1.1\r\nHost: x\r\n\r\n",
                    b"POST /show?picture=" + quoted.lower() + b"&x=a b HTTP/1.1\r\nHost: x\r\n\r\n",
                    b"GET /status?picture=" + quoted + b" HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer " + raw +
                    b"\r\n\r\n"]
        try:
            with self.assertLogs(level="DEBUG") as logged:
                logging.getLogger(__name__).debug("the calls")
                for request in requests:
                    reader, writer = await asyncio.open_connection(client.host, client.port)
                    writer.write(request)
                    await writer.drain()
                    await reader.readline()
                    writer.close()
                await asyncio.sleep(0.2)
        finally:
            await client.close()
        text = "\n".join(logged.output).lower()
        for form in (self.OWN, repr(raw)[2:-1], quoted.decode()):
            with self.subTest(form=form):
                self.assertTrue(form.lower() not in text, "a form of the key is in the log")


if __name__ == "__main__":
    unittest.main()
