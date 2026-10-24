import asyncio, base64, json, ssl, sys, time, websockets
async def main(url):
    t=time.time(); ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
    async with websockets.connect(url, ssl=ctx if url.startswith("wss") else None, open_timeout=10) as ws:
        m = await asyncio.wait_for(ws.recv(), 70); print(round(time.time()-t,1), "s:", m[:300])
name = base64.b64encode(b"FrameArt").decode()
for u in ["ws://10.1.2.36:8001/api/v2/channels/samsung.remote.control?name="+name,
          "wss://10.1.2.36:8002/api/v2/channels/samsung.remote.control?name="+name]:
    try: asyncio.run(main(u))
    except Exception as e: print(u[:40], "ERR", repr(e))
