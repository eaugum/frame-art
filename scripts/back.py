"""Tries the way back from Art Mode (AUG-1494): when the art channel says art_mode_changed off after on, Frame TV is
started over the remote control channel. That's the only thing it sends.

    python scripts/back.py 10.1.2.36 [seconds] [app id]
"""
import asyncio, datetime, json, logging, sys
from samsungtvws.async_art import SamsungTVAsyncArt
from samsungtvws.async_remote import SamsungTVWSAsyncRemote
from samsungtvws.remote import ChannelEmitCommand


def say(*a):
    print(datetime.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


async def launch(ip, app):
    remote = SamsungTVWSAsyncRemote(host=ip, port=8002, token_file="token.txt", name="FrameArt", timeout=30)
    try:
        await asyncio.wait_for(remote.start_listening(), 40)
        await remote.send_command(ChannelEmitCommand.launch_app(app))
        say("sent ed.apps.launch", app)
        await asyncio.sleep(3)
    finally:
        await remote.close()


async def main(ip, seconds, app):
    tv = SamsungTVAsyncArt(host=ip, port=8002, token_file="token.txt", name="FrameArt")
    seen, was_on, tasks = tv.process_event, [False], []

    async def watch(event=None, response=None):
        try:
            sub = json.loads(response["data"]).get("event") if event == "d2d_service_message" else None
            status = json.loads(response["data"]).get("status")
        except Exception:
            sub = status = None
        say(event, sub or "", status or "")
        if sub == "art_mode_changed" and status == "on":
            was_on[0] = True
        elif sub == "art_mode_changed" and status == "off" and was_on[0]:
            was_on[0] = False
            tasks.append(asyncio.create_task(launch(ip, app)))
        await seen(event, response)

    tv.process_event = watch
    await tv.start_listening()
    say("listening for %d s" % seconds)
    await asyncio.sleep(seconds)
    for t in tasks:
        await t
    await tv.close()


logging.basicConfig(level=logging.WARNING)
asyncio.run(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 180,
                 sys.argv[3] if len(sys.argv) > 3 else "FrameTVapp.FrameTV"))
