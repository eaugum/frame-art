"""HTTP with the standard library. Wikimedia and the museums ask for a User-Agent that says who we are."""
import json
import urllib.parse
import urllib.request

from . import __version__

USER_AGENT = "frame-art/%s (https://github.com/eaugum/frame-tv)" % __version__


def get(url, params=None, accept=None, timeout=60):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        return r.read()


def get_json(url, params=None, accept="application/json"):
    return json.loads(get(url, params, accept))
