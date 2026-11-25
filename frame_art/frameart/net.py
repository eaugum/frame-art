"""HTTP with the standard library. Wikimedia and the museums ask for a User-Agent that says who we are.

Only http(s). The first address may be on the home network (Home Assistant, a Stasera of one's own); after that, an
address on another origin (a redirect, or with home one an answer chose) must be public, after the name is looked up,
and the connection goes to the address that was checked. A token (Authorization) is never sent on to another origin.
Every request has a cap on the bytes read and a deadline for all of it, redirects included."""
import http.client
import io
import ipaddress
import json
import socket
import threading
import time
import urllib.error
import urllib.parse

from . import __version__

USER_AGENT = "frame-art/%s (https://github.com/eaugum/frame-art)" % __version__
LIMIT = 100 * 2 ** 20  # a picture: a museum's original can be 50 MB
JSON_LIMIT = 20 * 2 ** 20
REDIRECTS = 5
NAT64 = ipaddress.ip_network("64:ff9b::/96")


class Refused(urllib.error.URLError):
    """An address we don't go to, or an answer we don't take (too big)."""


def internal(ip):
    """Loopback, private, link-local, CGNAT, the Supervisor's network, multicast...: anything not on the internet."""
    ip = ipaddress.ip_address(ip.split("%")[0])
    if ip.version == 6:
        ip = ip.ipv4_mapped or ip.sixtofour or ip
    if ip.version == 6 and (ip in NAT64 or int(ip) >> 32 == 0):  # 64:ff9b::a.b.c.d, ::a.b.c.d
        ip = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return not ip.is_global or ip.is_multicast


def origin(url):
    p = urllib.parse.urlsplit(url)
    scheme = p.scheme.lower()
    return scheme, (p.hostname or "").lower(), p.port or {"http": 80, "https": 443}.get(scheme)


def _connect(allowed, address, timeout):
    """A socket to one of the host's addresses; none of them may be internal unless the origin is allowed."""
    host, port = address
    found = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not allowed and any(internal(a[4][0]) for a in found):
        raise Refused("%s is on the home network" % host)
    error = OSError("no address for %s" % host)
    for family, kind, proto, _, addr in found:
        sock = socket.socket(family, kind, proto)
        try:
            sock.settimeout(timeout)
            sock.connect(addr)
            return sock
        except OSError as e:
            sock.close()
            error = e
    raise error


class _Checked:
    """A socket timeout is per read, and a byte now and then renews it: at the deadline the connection is shut down,
    which ends a read in any part of the answer (TLS, status line, headers, chunks, body)."""

    def __init__(self, host, port, allowed, **kwargs):
        super().__init__(host, port, **kwargs)
        self.allowed, self.spare, self.late = allowed, None, False
        self._create_connection = self._open

    def _open(self, address, timeout, source=None):
        sock = _connect(self.allowed, address, timeout)
        self.spare = sock.dup()  # still this connection after TLS takes over the socket
        if self.late:
            self.stop()
        return sock

    def stop(self):
        self.late = True
        if self.spare:
            try:
                self.spare.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def close(self):
        super().close()
        if self.spare:
            self.spare.close()


class _HTTP(_Checked, http.client.HTTPConnection):
    pass


class _HTTPS(_Checked, http.client.HTTPSConnection):
    pass


def _read(r, conn, limit, deadline):
    if (r.length or 0) > limit:
        raise Refused("an answer of more than %d bytes" % limit)
    out = bytearray()
    while not r.isclosed():  # closed: all of it read
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("the answer took too long")
        chunk = r.read1(65536)
        if not chunk:
            break
        out += chunk
        if len(out) > limit:
            raise Refused("an answer of more than %d bytes" % limit)
    if conn.late:  # shut down at the deadline: what's here is only part of it
        raise TimeoutError("the answer took too long")
    if r.length:  # read1 ends quietly when the connection does, before Content-Length
        raise http.client.IncompleteRead(bytes(out), r.length)
    return bytes(out)


def request(url, data=None, method="GET", headers=None, timeout=60, limit=LIMIT, home=None):
    """(status, body). Raises urllib.error.HTTPError for 4xx and 5xx, Refused, or what the connection raises.
    home: the origin the caller trusts, when url came from an answer (by default url's own)."""
    deadline = time.monotonic() + timeout
    first = origin(url)
    trusted = origin(home) if home else first
    headers = dict(headers or {})
    for _ in range(REDIRECTS + 1):
        scheme, host, port = where = origin(url)
        if scheme not in ("http", "https") or not host:
            raise Refused("only http(s) addresses")
        if where != first and any(k.lower() == "authorization" for k in headers):
            raise Refused("not sending the token on to %s://%s" % (scheme, host))
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("took too long")
        conn = (_HTTPS if scheme == "https" else _HTTP)(host, port, where == trusted, timeout=left)
        watch = threading.Timer(left, conn.stop)
        watch.daemon = True
        watch.start()
        try:
            parts = urllib.parse.urlsplit(url)
            conn.request(method, (parts.path or "/") + ("?" + parts.query if parts.query else ""), data, headers)
            r = conn.getresponse()
            location = r.getheader("Location")
            if r.status in (301, 302, 303, 307, 308) and location and method in ("GET", "HEAD"):
                url = urllib.parse.urljoin(url, location)
                continue
            body = _read(r, conn, limit, deadline)
        except (OSError, http.client.HTTPException) as e:
            if conn.late and not isinstance(e, Refused):
                raise TimeoutError("took too long") from None
            raise
        finally:
            watch.cancel()
            conn.close()
        if r.status >= 400:
            raise urllib.error.HTTPError(url, r.status, r.reason, r.headers, io.BytesIO(body))
        return r.status, body
    raise Refused("too many redirects")


def get(url, params=None, accept=None, timeout=60, headers=None, limit=LIMIT, home=None):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
    headers = dict(headers or {}, **{"User-Agent": USER_AGENT})
    if accept:
        headers["Accept"] = accept
    for attempt in range(4):
        try:
            return request(url, headers=headers, timeout=timeout, limit=limit, home=home)[1]
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or attempt == 3:  # too many at once: Commons, when it lists a big tree
                raise
            wait = e.headers.get("Retry-After") or ""
            time.sleep(min(int(wait), 120) if wait.isdigit() else 15 * (attempt + 1))


def get_json(url, params=None, accept="application/json", home=None):
    return json.loads(get(url, params, accept, limit=JSON_LIMIT, home=home))
