"""Følg musikken (AUG-1495): what Spotify plays, read from Home Assistant, without a Spotify token of our own.

In the add-on, Home Assistant is the Supervisor's proxy (homeassistant_api: true in config.yaml); outside it, ha_url and
ha_token in the options. The player is the first media_player.spotify* (Spotify or SpotifyPlus) that plays.
"""
import json
import os
import urllib.request

from . import net

PLAYER = "media_player.spotify"
PLAYERS_SECONDS = 3600  # the list of players is looked up again this often
BIG = ("ab67616d0000b273", "ab67616d000082c1")  # Spotify's 640 px cover id, and the same cover at 2000 px


class HomeAssistant:
    def __init__(self, cfg):
        token = os.environ.get("SUPERVISOR_TOKEN")
        if token:
            self.url, self.token = "http://supervisor/core", token
        else:
            self.url, self.token = (cfg.get("ha_url") or "").rstrip("/"), cfg.get("ha_token")
        self.players, self.players_at = [], 0
        self.last_cover = (None, None)  # (url, bytes): the next song on the album needs no download

    def ready(self):
        return bool(self.url and self.token)

    def get(self, path, timeout=10):
        req = urllib.request.Request(self.url + path, headers={"Authorization": "Bearer " + self.token})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    def state(self, entity_id):
        return json.loads(self.get("/api/states/" + entity_id))

    def _players(self, now):
        if not self.players or now - self.players_at > PLAYERS_SECONDS:
            states = json.loads(self.get("/api/states", timeout=30))
            self.players = sorted(s["entity_id"] for s in states if s["entity_id"].startswith(PLAYER))
            self.players_at = now
        return self.players

    def home(self):
        """Someone at home: zone.home counts the people in it; without that, a person.* that's home."""
        try:
            return int(self.state("zone.home")["state"]) > 0
        except (ValueError, KeyError):
            states = json.loads(self.get("/api/states", timeout=30))
            return any(s["entity_id"].startswith("person.") and s["state"] == "home" for s in states)

    def playing(self, now):
        """{key, album, artist, title, cover, entity} for what plays, or None."""
        for entity in self._players(now):
            s = self.state(entity)
            a = s.get("attributes") or {}
            if s.get("state") != "playing" or a.get("media_content_type") not in (None, "music"):
                continue
            cover = a.get("sp_nowplaying_image_url") or a.get("entity_picture") or ""
            # one picture per song: Spotify's track id, or the title where there's none
            track = a.get("media_content_id") or ""
            key = track.rsplit(":", 1)[-1] if track.startswith("spotify:") else "%s/%s" % (a.get("media_title"),
                                                                                         a.get("media_artist"))
            return {"key": "music:" + key, "album": a.get("media_album_name") or a.get("media_title") or "",
                    "artist": a.get("media_artist") or "", "title": a.get("media_title") or "", "cover": cover,
                    "entity": entity}
        return None

    def cover(self, url):
        """The cover's bytes, as big as Spotify has it; a path from Home Assistant (entity_picture) goes through it."""
        if self.last_cover[0] == url:
            return self.last_cover[1]
        data = self._cover(url)
        self.last_cover = (url, data)
        return data

    def _cover(self, url):
        if url.startswith("/"):
            return self.get(url, timeout=30)
        if url.startswith("https://i.scdn.co/image/" + BIG[0]):
            try:
                return net.get(url.replace(BIG[0], BIG[1]), timeout=30)
            except Exception:
                pass
        return net.get(url, timeout=30)
