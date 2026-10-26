"""python -m frameart [--config options.json] [--data dir] [--once | --preview dir] [--what morning|tonight]

Running, it changes the picture on its own and answers on api_port (8099; 0 = no API), see api.py.

In the Home Assistant add-on, the options are /data/options.json and the state stays in /data.
"""
import argparse
import asyncio
import json
import logging
import os

from . import api, mqtt
from .service import Rotation


def main():
    p = argparse.ArgumentParser(prog="frameart")
    p.add_argument("--config", default="/data/options.json")
    p.add_argument("--data", help="token, state and the next picture (default: the config's folder)")
    p.add_argument("--once", action="store_true", help="change the picture once and stop")
    p.add_argument("--preview", metavar="DIR", help="save a few pictures here instead of sending them to the TV")
    p.add_argument("-n", type=int, default=5, help="how many pictures --preview makes")
    p.add_argument("--what", choices=("morning", "tonight"), help="Morgenbildet or tonight's poster, not the rotation")
    a = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    logging.getLogger("samsungtvws").setLevel(logging.WARNING)  # it logs the TV's token at INFO
    with open(a.config) as f:
        cfg = json.load(f)
    data = a.data or os.path.dirname(os.path.abspath(a.config))
    os.makedirs(data, exist_ok=True)
    rot = Rotation(cfg, data)

    if a.preview:
        os.makedirs(a.preview, exist_ok=True)
        for i in range(1 if a.what else a.n):
            got = rot.make(a.what) if a.what else rot.pick()
            if not got:
                break
            path = os.path.join(a.preview, "%d-%s.jpg" % (i + 1, got[2].split(":")[0]))
            with open(path, "wb") as f:
                f.write(got[0])
            logging.info("%s -> %s", got[1], path)
        rot.state.save()
    elif a.once:
        asyncio.run(rot.change(what=a.what))
    else:
        asyncio.run(run(rot, cfg, int(cfg.get("api_port", 8099))))


async def run(rot, cfg, port):
    if port:
        await api.serve(rot, port)
    device = asyncio.create_task(mqtt.serve(rot, cfg))  # Home Assistant, when there's a broker
    try:
        await rot.run()
    finally:
        device.cancel()


main()
