"""AUG-1772: net.get goes only to http(s), checks every redirect, and has a cap on bytes and a deadline; Stasera's token
goes only to Stasera; a service's next page is an http(s) address."""
import http.client
import http.server
import json
import os
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest import mock

import fakes
from frameart import net, sources, stasera

PUBLIC = "127.0.0.2"  # a second loopback address, counted as public in these tests
_internal = net.internal


def internal(ip):
    return ip != PUBLIC and _internal(ip)


class Server(http.server.ThreadingHTTPServer):
    """A local server; routes: path -> (status, headers, body), or a function of the handler. Keeps what it was asked,
    with the Authorization header."""

    def __init__(self, host="127.0.0.1", routes=None):
        self.routes = routes or {}
        self.asked = []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                server.asked.append((self.path, self.headers.get("Authorization")))
                route = server.routes.get(self.path.split("?")[0], (404, {}, b"no"))
                if callable(route):
                    return route(self)
                status, headers, body = route
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        super().__init__((host, 0), Handler)
        self.url = "http://%s:%d" % (host, self.server_address[1])
        threading.Thread(target=self.serve_forever, daemon=True).start()


class Servers(unittest.TestCase):
    def server(self, host="127.0.0.1", routes=None):
        s = Server(host, routes)
        self.addCleanup(s.server_close)
        self.addCleanup(s.shutdown)
        return s

    def setUp(self):
        patch = mock.patch.object(net, "internal", internal)
        patch.start()
        self.addCleanup(patch.stop)


def moved(to):
    return (302, {"Location": to}, b"")


class InternalTest(unittest.TestCase):
    def test_addresses(self):
        for ip, want in [("127.0.0.1", True), ("10.1.2.3", True), ("172.16.0.1", True), ("172.30.32.2", True),
                         ("192.168.1.50", True), ("169.254.169.254", True), ("100.64.0.1", True), ("0.0.0.0", True),
                         ("::1", True), ("fc00::1", True), ("fe80::1%eth0", True), ("::ffff:10.0.0.1", True),
                         ("::ffff:127.0.0.1", True), ("2002:a00:1::", True), ("224.0.0.1", True),
                         ("64:ff9b::7f00:1", True), ("64:ff9b::a00:1", True), ("::127.0.0.1", True),
                         ("64:ff9b::808:808", False), ("8.8.8.8", False), ("151.101.1.1", False), ("2606:4700::1111", False)]:
            with self.subTest(ip=ip):
                self.assertIs(_internal(ip), want)


class GetTest(Servers):
    def test_only_http(self):
        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            f.write(b'{"x": 1}')
            f.flush()
            for url in ("file://" + f.name, "ftp://127.0.0.1/x", "data:,hello", "/relative"):
                with self.subTest(url=url):
                    with self.assertRaises(net.Refused):
                        net.get(url)

    def test_redirects(self):
        other = self.server()  # internal, another origin
        public = self.server(PUBLIC, {"/ok": (200, {}, b"public")})
        other.routes["/ok"] = (200, {}, b"internal")
        home = self.server()
        home.routes.update({"/ok": (200, {}, b"home"), "/same": moved("/ok"), "/public": moved(public.url + "/ok"),
                            "/internal": moved(other.url + "/ok"), "/file": moved("file:///etc/hostname"),
                            "/loop": moved("/loop"),
                            "/name": moved("http://camera.test:%d/ok" % other.server_address[1])})
        self.assertEqual(net.get(home.url + "/same"), b"home")
        self.assertEqual(net.get(home.url + "/public"), b"public")
        real = socket.getaddrinfo
        names = lambda host, *a, **k: real("127.0.0.1" if host == "camera.test" else host, *a, **k)
        with mock.patch("socket.getaddrinfo", names):
            for path in ("/internal", "/file", "/name", "/loop"):
                with self.subTest(path=path):
                    with self.assertRaises(net.Refused):
                        net.get(home.url + path)
        self.assertEqual(other.asked, [])

    def test_home(self):
        """An address an answer chose may be internal only on the service's own origin."""
        service = self.server(routes={"/img": (200, {}, b"own")})
        other = self.server(routes={"/img": (200, {}, b"other")})
        self.assertEqual(net.get(service.url + "/img", home=service.url + "/search?q=x"), b"own")
        with self.assertRaises(net.Refused):
            net.get(other.url + "/img", home=service.url + "/search?q=x")
        self.assertEqual(other.asked, [])

    def test_cap(self):
        def chunked(h):  # no Content-Length: the cap counts what's read
            h.send_response(200)
            h.send_header("Transfer-Encoding", "chunked")
            h.end_headers()
            try:
                for _ in range(20):
                    h.wfile.write(b"400\r\n" + b"x" * 1024 + b"\r\n")
                h.wfile.write(b"0\r\n\r\n")
            except OSError:  # the client stopped reading
                pass

        s = self.server(routes={"/big": (200, {}, b"x" * 5000), "/chunked": chunked})
        self.assertEqual(len(net.get(s.url + "/big", limit=5000)), 5000)
        for path in ("/big", "/chunked"):
            with self.subTest(path=path):
                with self.assertRaises(net.Refused):
                    net.get(s.url + path, limit=4096)

    def test_deadline_for_the_whole_request(self):
        def drip(h):
            h.send_response(200)
            h.send_header("Content-Length", "100")
            h.end_headers()
            try:
                for _ in range(100):
                    h.wfile.write(b"x")
                    h.wfile.flush()
                    time.sleep(0.2)
            except OSError:
                pass

        s = self.server(routes={"/drip": drip})
        start = time.time()
        with self.assertRaises(OSError):
            net.get(s.url + "/drip", timeout=1)
        self.assertLess(time.time() - start, 2)

    def test_deadline_in_every_part_of_the_answer(self):
        """A byte now and then keeps each read alive; the deadline is for the whole request."""
        def slowly(h, data):
            try:
                for i in range(len(data)):
                    h.wfile.write(data[i:i + 1])
                    h.wfile.flush()
                    time.sleep(0.15)
            except OSError:
                pass

        status = lambda h: slowly(h, b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        headers = lambda h: (h.wfile.write(b"HTTP/1.1 200 OK\r\n"), slowly(h, b"X-Slow: " + b"x" * 30 + b"\r\n"
                                                                             b"Content-Length: 2\r\n\r\nok"))
        chunks = lambda h: (h.wfile.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"),
                            slowly(h, b"1;" + b"x" * 30 + b"\r\nx\r\n0\r\n\r\n"))
        s = self.server(routes={"/status": status, "/headers": headers, "/chunks": chunks,
                                "/redirect": moved("/headers")})
        for path in ("/status", "/headers", "/chunks", "/redirect"):
            with self.subTest(path=path):
                start = time.time()
                with self.assertRaises(OSError):
                    net.get(s.url + path, timeout=1)
                self.assertLess(time.time() - start, 1.5)

    def test_a_short_answer_isnt_taken(self):
        """Closed before Content-Length, or cut at the deadline mid-body: an error, never half a picture."""
        def short(h):
            h.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n" + b"x" * 10)

        def stuck(h):
            h.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n" + b"x" * 10)
            h.wfile.flush()
            time.sleep(3)

        def unsized(h):  # HTTP/1.0 without Content-Length: the answer ends when the connection does
            h.wfile.write(b"HTTP/1.0 200 OK\r\n\r\n")
            try:
                for _ in range(15):  # a byte now and then: only the deadline ends it
                    h.wfile.write(b"x")
                    h.wfile.flush()
                    time.sleep(0.2)
            except OSError:
                pass

        s = self.server(routes={"/short": short, "/stuck": stuck, "/unsized": unsized})
        for path in ("/short", "/stuck", "/unsized"):
            with self.subTest(path=path):
                with self.assertRaises((OSError, http.client.HTTPException)):
                    net.get(s.url + path, timeout=1)

    def test_errors_and_json(self):
        s = self.server(routes={"/gone": (404, {}, b"{}"), "/j": (200, {}, b'{"a": [1]}')})
        with self.assertRaises(urllib.error.HTTPError) as e:
            net.get(s.url + "/gone")
        self.assertEqual(e.exception.code, 404)
        self.assertEqual(net.get_json(s.url + "/j"), {"a": [1]})


class StaseraTest(Servers):
    def stasera(self, base):
        data = tempfile.mkdtemp()
        with open(os.path.join(data, "stasera_token.txt"), "w") as f:
            f.write(fakes.FAKE_TOKEN)
        return stasera.Stasera(base, data)

    def test_ask_only_under_the_base(self):
        s = self.stasera("https://www.stasera.app")
        with mock.patch.object(s, "_request", return_value=(200, {})) as request:
            for url in ("https://xxxxxxxxxxxxxxx.attacker.example/a", "https://www.stasera.app.attacker.example/a",
                        "https://stasera.app/tv/home", "http://www.stasera.app/tv/home"):
                with self.subTest(url=url):
                    with self.assertRaises(RuntimeError):
                        s.ask(url)
            request.assert_not_called()
            s.ask("https://www.stasera.app/tv/home?parts=watching")
        request.assert_called_once_with("GET", "/tv/home?parts=watching")

    def test_token_doesnt_follow_a_redirect_elsewhere(self):
        elsewhere = self.server(PUBLIC, {"/tv/home": (200, {}, b"{}")})
        home = self.server(routes={"/tv/home": moved(elsewhere.url + "/tv/home"), "/tv/x": moved("/tv/y"),
                                   "/tv/y": (200, {}, b'{"ok": true}')})
        s = self.stasera(home.url)
        with self.assertRaises(Exception):
            s.ask(home.url + "/tv/home")
        self.assertEqual(elsewhere.asked, [])
        self.assertEqual(s.token(), fakes.FAKE_TOKEN)  # kept
        self.assertEqual(s.ask(home.url + "/tv/x"), {"ok": True})  # the same origin is fine
        self.assertEqual(home.asked[-1], ("/tv/y", "Bearer " + fakes.FAKE_TOKEN))


class NextTest(Servers):
    def test_next_is_an_http_address(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"items": [{"id": "from-a-file"}]}, f)
        self.addCleanup(os.remove, f.name)
        s = self.server()
        s.routes["/search"] = (200, {}, json.dumps({"items": [{"id": "a"}], "next": "file://" + f.name}).encode())
        src = sources.from_config({"services": [{"name": "svc", "url": s.url + "/search?q={query}", "items": "items",
                                                 "next": "next", "steps": [s.url + "/o/{id}"],
                                                 "image": "{step1.image}"}],
                                   "sources": [{"name": "Svc", "type": "svc"}]})[0]
        self.assertEqual(src.keys(), ["a"])


if __name__ == "__main__":
    unittest.main()
