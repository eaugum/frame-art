"""Prints everything the Frame's art channel says for a few minutes (AUG-1494). Sends nothing, changes nothing.

    python scripts/listen.py 10.1.2.36 [seconds]
"""
import asyncio, datetime, json, logging, sys
from samsungtvws.async_art import SamsungTVAsyncArt


async def main(ip, seconds):
    tv = SamsungTVAsyncArt(host=ip, port=8002, token_file="token.txt", name="FrameArt")
    seen = tv.process_event

    async def show(event=None, response=None):
        print(datetime.datetime.now().strftime("%H:%M:%S"), event, json.dumps(response, default=str)[:600], flush=True)
        await seen(event, response)

    tv.process_event = show
    await tv.start_listening()
    print("listening for %d s; do what you want to on the TV now" % seconds, flush=True)
    await asyncio.sleep(seconds)
    await tv.close()


logging.basicConfig(level=logging.WARNING)
asyncio.run(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 180))
