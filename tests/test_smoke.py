"""The harness can drive the add-on without a TV or Home Assistant: the patterns later tests build on."""
import json
import os
import tempfile
import unittest
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

import fakes
from frameart import __version__, api, events, music
from frameart.service import Rotation, State


class Temp(unittest.TestCase):
    """A data folder and a folder of pictures, removed afterwards; no Supervisor in the environment."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = os.path.join(tmp.name, "data")
        os.makedirs(self.data)
        self.pictures = fakes.pictures(os.path.join(tmp.name, "pictures"))
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("SUPERVISOR_TOKEN", None)
        events.setup(self.data)

    def rotation(self, **more):
        return Rotation(fakes.options(self.pictures, **more), self.data)


class StateTest(Temp):
    def test_defaults_and_save(self):
        path = os.path.join(self.data, "state.json")
        state = State(path)
        self.assertEqual(state["uploaded"], [])
        state["changed"] = 123
        state.save()
        self.assertEqual(State(path)["changed"], 123)


class HomeAssistantTest(Temp):
    def test_playing_from_a_fake(self):
        states = [{"entity_id": "media_player.spotify_us", "state": "playing",
                   "attributes": {"media_content_id": "spotify:track:abc", "media_title": "Song",
                                  "media_artist": "Artist", "media_album_name": "Album", "entity_picture": "/c.jpg"}},
                  {"entity_id": "light.kitchen", "state": "on"}]
        fake = fakes.FakeUrlopen({"/api/states": states, "/api/states/media_player.spotify_us": states[0]})
        ha = music.HomeAssistant({"ha_url": fakes.FAKE_HA, "ha_token": fakes.FAKE_TOKEN})
        with mock.patch("urllib.request.urlopen", fake):
            got = ha.playing(now=1000)
        self.assertEqual(got["key"], "music:abc")
        self.assertEqual(got["album"], "Album")
        self.assertEqual(fake.requests[0].get_header("Authorization"), "Bearer " + fakes.FAKE_TOKEN)


class RotationTest(Temp):
    def test_status_and_pick(self):
        rot = self.rotation()
        self.assertEqual(rot.status()["version"], __version__)
        self.assertEqual(rot.status()["sources"], ["My pictures"])
        jpeg, label, key = rot.pick()
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))
        self.assertTrue(key.startswith("My pictures:sample-"))


class ApiTest(Temp, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = TestClient(TestServer(api.app(self.rotation())))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_status_needs_the_key(self):
        r = await self.client.get("/status")
        self.assertEqual(r.status, 401)
        r = await self.client.get("/status", headers={"Authorization": "Bearer " + fakes.FAKE_KEY})
        self.assertEqual(r.status, 200)
        self.assertEqual((await r.json())["version"], __version__)

    async def test_page_through_ingress(self):
        with mock.patch.object(api, "INGRESS", "127.0.0.1"):  # the test client is the Supervisor
            page = await self.client.get("/")
            status = await self.client.get("/status")
        self.assertEqual(page.status, 200)
        self.assertIn(json.dumps("New picture"), await page.text())  # i18n.PAGE went into the page
        self.assertEqual(status.status, 200)


if __name__ == "__main__":
    unittest.main()
