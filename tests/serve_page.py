"""The add-on's page and API against fakes, in a container from the test image (tests/serve_page.sh starts it).

The TV is a fake one (tests/fake_tv.py) on 127.0.0.1 in the container, so choosing a picture goes through the add-on's
real TV code; its log lines ("fake TV: ...") are in docker logs. There's no Home Assistant, MQTT or Stasera, and the
one source is a folder of sample pictures made here. Only the API runs, not the rotation or the watchers: choosing a
picture (/show) and a fixed picture need neither, and the rotation would change the picture by itself. The data (options.json,
state.json, settings.json) is in a temporary folder in the container.

The page works without the key only from the Supervisor (api.INGRESS); here the Supervisor is the address requests
come from through Docker's published port: the container's gateway, or FRAMEART_INGRESS.
"""
import asyncio
import logging
import os
import socket
import tempfile

import fake_tv
import fakes
from frameart import api, events
from frameart.service import Rotation

PORT = 8099  # the add-on's

_getaddrinfo = socket.getaddrinfo


def _here_only(host, *args, **kwargs):
    """Names are looked up only for this machine, so a stray call outside fails instead of leaving it."""
    if host not in (None, "", "0.0.0.0", "::", "127.0.0.1", "::1", "localhost"):
        raise OSError("serve_page: nothing outside this machine (%s)" % host)
    return _getaddrinfo(host, *args, **kwargs)


def gateway():
    """The default route's gateway, from /proc/net/route (hex, little-endian)."""
    with open("/proc/net/route") as f:
        for line in f.readlines()[1:]:
            fields = line.split()
            if fields[1] == "00000000":
                return socket.inet_ntoa(bytes.fromhex(fields[2])[::-1])
    raise RuntimeError("no default route")


async def main():
    data = tempfile.mkdtemp(prefix="frameart-page-")
    cfg = fakes.options(fakes.pictures(os.path.join(data, "pictures"), n=6))
    fakes.write_options(data, cfg)
    events.setup(data)
    with open(os.path.join(data, "token.txt"), "w") as f:  # a token, so the add-on doesn't ask the TV to pair
        f.write(fake_tv.TOKEN)
    tv = fake_tv.FakeTV()
    await tv.start()
    rot = Rotation(cfg, data)
    api.INGRESS = os.environ.get("FRAMEART_INGRESS") or gateway()
    logging.info("the page's requests count as ingress from %s; data in %s", api.INGRESS, data)
    await api.serve(rot, PORT)
    rot.reading.add("*")
    await asyncio.to_thread(rot.read_unlisted)  # the pictures' numbers on the page, as at the add-on's start
    await asyncio.Event().wait()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    socket.getaddrinfo = _here_only
    asyncio.run(main())
