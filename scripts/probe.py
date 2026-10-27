"""Reads the Art Mode status from the Frame. Changes nothing."""
import asyncio, json, logging, sys
from samsungtvws.async_art import SamsungTVAsyncArt

async def main(ip):
    tv = SamsungTVAsyncArt(host=ip, port=8002, token_file="token.txt", name="FrameArt")
    await tv.start_listening()
    out = {}
    for name, call in [("supported", tv.supported), ("api_version", tv.get_api_version),
                       ("artmode", tv.get_artmode), ("current", tv.get_current),
                       ("slideshow", tv.get_slideshow_status), ("available", tv.available)]:
        try:
            r = await asyncio.wait_for(call(), 40)
            out[name] = r if name != "available" else {"count": len(r), "sample": r[:5]}
        except Exception as e:
            out[name] = "ERROR: %r" % e
    print(json.dumps(out, indent=1, default=str))
    await tv.close()

logging.basicConfig(level=logging.WARNING)
asyncio.run(main(sys.argv[1]))
