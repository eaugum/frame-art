"""Makes one test picture (3840x2160) and uploads it to "My Photos". Doesn't show it."""
import asyncio, io, sys
from PIL import Image, ImageDraw
from samsungtvws.async_art import SamsungTVAsyncArt

def make():
    w, h = 3840, 2160
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):  # an evening sky over the Oslofjord
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(20 + 200 * t**2), int(30 + 90 * t**1.5), int(70 + 40 * t)))
    d.ellipse([w*0.62, h*0.52, w*0.62 + 360, h*0.52 + 360], fill=(255, 196, 120))
    d.rectangle([0, h*0.72, w, h], fill=(14, 22, 40))
    out = io.BytesIO(); img.save(out, "JPEG", quality=92); return out.getvalue()

async def main(ip):
    tv = SamsungTVAsyncArt(host=ip, port=8002, token_file="token.txt", name="FrameArt")
    await tv.start_listening()
    cid = await asyncio.wait_for(tv.upload(make(), file_type="JPEG", matte="none"), 120)
    print("uploaded:", cid)
    mine = [a for a in await tv.available() if a.get("category_id") == "MY-C0002"]
    print("my photos:", len(mine), [a["content_id"] for a in mine])
    await tv.close()
asyncio.run(main(sys.argv[1]))
