"""HTTP with the standard library. Wikimedia and the museums ask for a User-Agent that says who we are."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

USER_AGENT = "frame-art/%s (https://github.com/eaugum/frame-tv)" % __version__


def get(url, params=None, accept=None, timeout=60, headers=None):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    headers = dict(headers or {}, **{"User-Agent": USER_AGENT})
    if accept:
        headers["Accept"] = accept
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or attempt == 3:  # too many at once: Commons, when it lists a big tree
                raise
            wait = e.headers.get("Retry-After") or ""
            time.sleep(min(int(wait), 120) if wait.isdigit() else 15 * (attempt + 1))


def get_json(url, params=None, accept="application/json"):
    return json.loads(get(url, params, accept))
