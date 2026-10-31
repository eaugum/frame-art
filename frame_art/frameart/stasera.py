"""Stasera (stasera.app), for the poster of tonight's show. The add-on is linked once like a TV: a code from
POST /tv/pair/start, approved on the phone, and the token stays in stasera_token.txt next to the TV's token.
"""
import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.request

from .net import USER_AGENT

log = logging.getLogger(__name__)

POLL_SECONDS = 3


class Unlinked(Exception):
    """No token, or Stasera no longer takes it (unlinked on the phone)."""


class Stasera:
    def __init__(self, url, data_dir, name="Frame Art"):
        self.base = (url or "").rstrip("/")
        self.token_path = os.path.join(data_dir, "stasera_token.txt")
        self.name = name
        self.pairing = None  # {code, url, expiresAt} while a code waits for approval
        self._poller = None

    @property
    def on(self):
        return bool(self.base)

    def token(self):
        try:
            with open(self.token_path) as f:
                return f.read().strip() or None
        except OSError:
            return None

    def state(self):
        if not self.on:
            return "off"
        if self.token():
            return "linked"
        return "pairing" if self.pairing else "unlinked"

    def _request(self, method, path, body=None, auth=True):
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if auth:
            token = self.token()
            if not token:
                raise Unlinked()
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            if e.code == 401 and auth:
                log.warning("Stasera no longer takes the token; link again from the add-on's page")
                self.unlink()
                raise Unlinked()
            try:
                return e.code, json.loads(e.read() or b"null")
            except ValueError:
                return e.code, None

    # MARK: - Linking

    async def link(self):
        """A new code; the add-on's page shows it until it's approved on the phone or runs out."""
        try:
            status, j = await asyncio.to_thread(self._request, "POST", "/tv/pair/start",
                                                {"name": self.name, "type": "homeassistant"}, False)
        except Exception as e:  # DNS, no route, TLS
            raise RuntimeError("no answer from %s (%s)" % (self.base, e))
        if status == 429:
            raise RuntimeError("Stasera is busy, try again in a minute")
        if status != 200 or not isinstance(j, dict) or not j.get("secret"):
            raise RuntimeError("%s/tv/pair/start answered %s; stasera_url should be https://www.stasera.app"
                               % (self.base, status))
        self.pairing = {"code": j["code"], "url": j["url"], "expiresAt": j["expiresAt"]}
        if self._poller:
            self._poller.cancel()
        self._poller = asyncio.create_task(self._poll(j["secret"], j["expiresAt"]))
        log.info("Stasera: approve code %s at %s", j["code"], j["url"])
        return self.pairing

    async def _poll(self, secret, expires_at):
        try:
            while time.time() * 1000 < expires_at:
                await asyncio.sleep(POLL_SECONDS)
                try:
                    status, j = await asyncio.to_thread(self._request, "POST", "/tv/pair/poll", {"secret": secret},
                                                        False)
                except Exception as e:
                    log.info("Stasera: couldn't ask about the code (%s)", e)
                    continue
                if status == 200 and j and j.get("status") == "approved" and j.get("token"):
                    with open(self.token_path, "w") as f:
                        f.write(j["token"])
                    log.info("Stasera: linked")
                    return
                if status == 410:
                    break
            log.info("Stasera: the code ran out")
        finally:
            self.pairing = None
            self._poller = None

    def unlink(self):
        try:
            os.remove(self.token_path)
        except OSError:
            pass

    # MARK: - What we watch

    def ask(self, url):
        """An address on Stasera, as the linked add-on. Raises Unlinked."""
        path = url[len(self.base):]
        status, j = self._request("GET", path)
        if status != 200:
            raise RuntimeError("Stasera answered %s to %s" % (status, path))
        return j

    def titles(self, lists):
        """Titles from Stasera's lists: watching, wantToStart and movies (/tv/home) and recommendations, each
        {kind, tmdbId, title, year, backdropPath, textlessBackdropPath?, logoPath?, list}. Raises Unlinked."""
        out = []
        home = [l for l in lists if l in ("watching", "wantToStart", "movies")]
        if home:
            status, j = self._request("GET", "/tv/home?parts=" + ",".join(home))
            if status != 200 or not j:
                raise RuntimeError("Stasera answered %s" % status)
            for l in home:
                out += [dict(t, list=l) for t in j.get(l) or []]
        if "recommendations" in lists:
            status, j = self._request("GET", "/tv/recommendations")
            if status != 200 or not j:
                raise RuntimeError("Stasera answered %s" % status)
            out += [dict(t, list="recommendations") for t in j.get("items") or []]
        return out

    def upcoming(self, today, days=1):
        """What's coming from `today` (the TV's date, YYYY-MM-DD) and `days` on: episodes and films, each with its
        date. Raises Unlinked."""
        status, j = self._request("GET", "/tv/upcoming?today=%s&days=%d" % (today, days))
        if status != 200 or not j:
            raise RuntimeError("Stasera answered %s" % status)
        return j.get("items") or []

    # MARK: - Tonight

    def tonight(self):
        """Stasera's "Tonight", first the one to watch: shows with the next episode, and movies. Raises Unlinked."""
        status, j = self._request("GET", "/tv/tonight")
        if status != 200 or not j:
            raise RuntimeError("Stasera answered %s" % status)
        items = j.get("items") or []
        # /tv/home has the backdrop without text and the logo; /tv/tonight doesn't
        extra = {}
        try:
            status, h = self._request("GET", "/tv/home?parts=watching,movies")
            if status == 200 and h:
                for w in (h.get("watching") or []) + (h.get("movies") or []):
                    extra[(w.get("kind"), w.get("tmdbId"))] = w
        except Unlinked:
            raise
        except Exception as e:
            log.info("Stasera: no logos (%s)", e)
        for it in items:
            w = extra.get((it.get("kind"), it.get("tmdbId"))) or {}
            for k in ("textlessBackdropPath", "logoPath"):
                if w.get(k) and not it.get(k):
                    it[k] = w[k]
        return items
