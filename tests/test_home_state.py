"""AUG-1781: an unavailable or unknown home_entity or sleep_entity means "don't know", not nobody home or awake."""
import datetime
import time
import unittest
from unittest import mock

import fakes
from frameart import music, service
from test_smoke import Temp

DAY = datetime.datetime(2026, 11, 23, 14, 0)
NIGHT = datetime.datetime(2026, 11, 24, 3, 0)


class FakeHA:
    """Home Assistant's states by entity; a state that isn't there raises, like a missing entity."""

    def __init__(self, **states):
        self.ha = music.HomeAssistant({"ha_url": fakes.FAKE_HA, "ha_token": fakes.FAKE_TOKEN})
        self.states = states

    def __call__(self, req, timeout=None):
        entity = req.full_url.rsplit("/api/states/", 1)[1]
        routes = {"/api/states/" + entity: {"entity_id": entity, "state": self.states[entity], "attributes": {}}}
        return fakes.FakeUrlopen(routes)(req, timeout)


class HomeTest(Temp, unittest.TestCase):
    def home(self, entity, state):
        with mock.patch("urllib.request.urlopen", FakeHA(**{entity: state})):
            return FakeHA().ha.home(entity)

    def test_states(self):
        for entity, state, want in [
            ("person.me", "home", True), ("person.me", "not_home", False),
            ("binary_sensor.home", "on", True), ("binary_sensor.home", "off", False),
            ("binary_sensor.home", "unavailable", None), ("binary_sensor.home", "unknown", None),
            ("binary_sensor.home", "", None),
            ("zone.home", "2", True), ("zone.home", "0", False),
            ("zone.home", "unknown", None), ("zone.home", "unavailable", None)]:
            with self.subTest(entity=entity, state=state):
                self.assertIs(self.home(entity, state), want)


class GuardTest(Temp, unittest.IsolatedAsyncioTestCase):
    def make(self, at=DAY, **more):
        cfg = {"home_entity": "binary_sensor.home", "ha_url": fakes.FAKE_HA, "ha_token": fakes.FAKE_TOKEN}
        cfg.update(more)
        rot = self.rotation(**cfg)
        self.ha_states = {"binary_sensor.home": "on", "binary_sensor.asleep": "off", "zone.home": "1"}
        rot.now = lambda: at.replace(tzinfo=rot.zone)
        rot.calls = []

        async def turn_off(why, anything=False):
            rot.calls.append(("off", why))

        async def wake_for(kind, today):
            rot.calls.append(("wake", kind))

        rot.turn_off, rot._wake_for = turn_off, wake_for
        rot.seen["power"], rot.seen["art_mode"] = False, False
        return rot

    async def look(self, rot, **states):
        """One _guard with these states; the calls it made."""
        self.ha_states.update(states)
        del rot.calls[:]
        fake = FakeHA(**self.ha_states)
        with mock.patch("urllib.request.urlopen", fake):
            await rot._guard()
        return list(rot.calls)

    async def test_home_unavailable_home_by_day(self):
        rot = self.make()
        rot.seen["power"] = True
        self.assertEqual(await self.look(rot), [])
        self.assertEqual(await self.look(rot, **{"binary_sensor.home": "unavailable"}), [])
        rot.seen["power"] = False
        self.assertEqual(await self.look(rot, **{"binary_sensor.home": "on"}), [])

    async def test_home_unknown_home_at_night(self):
        rot = self.make(NIGHT)
        await self.look(rot)
        await self.look(rot, **{"binary_sensor.home": "unknown"})
        self.assertEqual(await self.look(rot, **{"binary_sensor.home": "on"}), [])

    async def test_away_unavailable_home_wakes(self):
        rot = self.make(NIGHT)
        await self.look(rot, **{"binary_sensor.home": "off"})
        self.assertEqual(await self.look(rot, **{"binary_sensor.home": "unavailable"}), [])
        self.assertEqual(await self.look(rot, **{"binary_sensor.home": "on"}), [("wake", None)])

    async def test_watching_then_unavailable_stays_on(self):
        rot = self.make()
        rot.seen["power"] = True
        await self.look(rot)
        self.assertEqual(await self.look(rot, **{"binary_sensor.home": "unavailable"}), [])

    async def test_real_away_turns_off(self):
        rot = self.make()
        rot.seen["power"] = True
        await self.look(rot)
        calls = await self.look(rot, **{"binary_sensor.home": "off"})
        self.assertEqual([c[0] for c in calls], ["off"])
        self.assertEqual(await self.look(rot, **{"binary_sensor.home": "off"}), calls)  # till the TV says off

    async def test_zone_unknown(self):
        rot = self.make(home_entity="zone.home")
        rot.seen["power"] = True
        await self.look(rot)
        self.assertEqual(await self.look(rot, **{"zone.home": "unknown"}), [])
        self.assertEqual(await self.look(rot, **{"zone.home": "1"}), [])
        rot.seen["power"] = False
        await self.look(rot, **{"zone.home": "0"})
        await self.look(rot, **{"zone.home": "unavailable"})
        self.assertEqual(await self.look(rot, **{"zone.home": "2"}), [("wake", None)])

    async def test_sleep_unavailable_keeps_the_night(self):
        rot = self.make(NIGHT, sleep_entity="binary_sensor.asleep")
        await self.look(rot, **{"binary_sensor.asleep": "on"})
        self.assertTrue(rot.was_night)
        rot.state["woke_at"] = 0
        self.assertEqual(await self.look(rot, **{"binary_sensor.asleep": "unavailable"}), [])
        self.assertEqual(await self.look(rot, **{"binary_sensor.asleep": "unknown"}), [])
        self.assertEqual(await self.look(rot, **{"binary_sensor.asleep": "on"}), [])
        self.assertEqual(rot.state["woke_at"], 0)
        self.assertTrue(rot.was_asleep)
        self.assertTrue(rot.was_night)

    async def test_real_wake_ends_the_night(self):
        rot = self.make(NIGHT, sleep_entity="binary_sensor.asleep")
        await self.look(rot, **{"binary_sensor.asleep": "on"})
        calls = await self.look(rot, **{"binary_sensor.asleep": "off"})
        self.assertEqual(calls, [("wake", None)])
        self.assertGreater(rot.state["woke_at"], 0)


class ListenTest(Temp, unittest.TestCase):
    def rot(self, **more):
        return self.rotation(home_entity="binary_sensor.home", ha_url=fakes.FAKE_HA, ha_token=fakes.FAKE_TOKEN,
                             music=True, **more)

    def step(self, rot, home, player, clock):
        """One look of follow(): what _listen sees, and what follow() does with it. player: what HA's player plays."""
        with mock.patch("urllib.request.urlopen", FakeHA(**{"binary_sensor.home": home})), \
                mock.patch.object(rot.ha, "playing", return_value=player), mock.patch("time.time", clock):
            now = rot._listen()
            if now:
                rot.music, rot.music_at = now, clock()
            return rot.playing()

    def test_playing_music_stays_while_home_is_unknown(self):
        rot, clock = self.rot(), mock.Mock(return_value=1000.0)
        self.assertTrue(self.step(rot, "on", {"key": "music:a"}, clock))
        clock.return_value += 4
        self.assertTrue(self.step(rot, "unavailable", {"key": "music:a"}, clock))
        self.assertEqual(rot.music, {"key": "music:a"})

    def test_song_change_is_followed_while_home_is_unknown(self):
        rot, clock = self.rot(), mock.Mock(return_value=1000.0)
        self.step(rot, "on", {"key": "music:a"}, clock)
        clock.return_value += 4
        self.assertTrue(self.step(rot, "unknown", {"key": "music:b"}, clock))
        self.assertEqual(rot.music, {"key": "music:b"})

    def test_music_lapses_after_the_grace_while_home_is_unknown(self):
        rot, clock = self.rot(), mock.Mock(return_value=1000.0)
        self.step(rot, "on", {"key": "music:a"}, clock)
        for _ in range(int(service.MUSIC_GRACE / 4) - 1):  # the player has stopped; home stays unavailable
            clock.return_value += 4
            playing = self.step(rot, "unavailable", None, clock)
        self.assertTrue(playing)
        for _ in range(3):
            clock.return_value += 4
            playing = self.step(rot, "unavailable", None, clock)
        self.assertFalse(playing)
        clock.return_value += 6 * 3600  # and stays stopped
        self.assertFalse(self.step(rot, "unavailable", None, clock))

    def test_no_music_is_not_started_while_home_is_unknown(self):
        rot, clock = self.rot(), mock.Mock(return_value=1000.0)
        for home in ("unknown", "unavailable"):
            self.assertFalse(self.step(rot, home, {"key": "music:b"}, clock))
        self.assertIsNone(rot.music)

    def test_lapsed_music_is_not_revived(self):
        rot, clock = self.rot(), mock.Mock(return_value=10000.0)
        rot.music, rot.music_at = {"key": "music:a"}, 1000.0
        self.assertFalse(self.step(rot, "unavailable", {"key": "music:a"}, clock))

    def test_away_is_still_not_listening(self):
        rot, clock = self.rot(), mock.Mock(return_value=1000.0)
        self.step(rot, "on", {"key": "music:a"}, clock)
        clock.return_value += service.MUSIC_GRACE + 1
        self.assertFalse(self.step(rot, "off", {"key": "music:a"}, clock))
