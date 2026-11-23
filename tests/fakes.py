"""Fakes for the tests and the page launcher: options, pictures and Home Assistant, nothing outside this machine."""
import io
import json
import os
from urllib.parse import urlsplit

from PIL import Image

FAKE_KEY = "FAKE-KEY-0000"  # the add-on's api_key
FAKE_TOKEN = "FAKE-TOKEN-0000"  # Home Assistant's token
FAKE_HA = "http://127.0.0.1:8123"


def pictures(folder, n=3, size=(1920, 1080)):
    """n plain 16:9 JPEGs in folder, for a folder source."""
    os.makedirs(folder, exist_ok=True)
    for i in range(n):
        Image.new("RGB", size, (60 * i % 256, 90, 160)).save(os.path.join(folder, "sample-%d.jpg" % (i + 1)))
    return folder


def options(pictures_dir, **more):
    """The add-on's options with the TV at 127.0.0.1, no Home Assistant, MQTT or Stasera, and one folder source."""
    cfg = {"tv_host": "127.0.0.1", "language": "en", "api_key": FAKE_KEY, "weather_entity": "", "home_entity": "",
           "sleep_entity": "", "calendars": [], "price_entity": "", "stasera_url": "", "back_app": "",
           "services": [],
           "sources": [{"category": "My pictures", "name": "My pictures", "type": "folder", "query": pictures_dir}]}
    cfg.update(more)
    return cfg


def write_options(data_dir, cfg):
    path = os.path.join(data_dir, "options.json")
    with open(path, "w") as f:
        json.dump(cfg, f, indent=1)
    return path


class Response(io.BytesIO):
    """What urllib.request.urlopen returns, enough for the add-on: read() in a with."""
    status = 200


class FakeUrlopen:
    """Stands in for urllib.request.urlopen: answers by path (a dict or list is sent as JSON) and keeps the requests.

        with mock.patch("urllib.request.urlopen", FakeUrlopen({"/api/states": [...]})) as fake: ...
    """

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        url = urlsplit(req.full_url if hasattr(req, "full_url") else req)
        if url.hostname not in ("127.0.0.1", "localhost"):
            raise AssertionError("a test asked outside this machine: %s" % url.geturl())
        if url.path not in self.routes:
            raise AssertionError("no fake answer for %s" % url.path)
        body = self.routes[url.path]
        return Response(body if isinstance(body, bytes) else json.dumps(body).encode())
