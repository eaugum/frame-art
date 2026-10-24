"""Kobler til fjernkontroll-kanalen (gir tilgangsspørsmål + token). Sender ingen taster."""
import asyncio, sys
from samsungtvws.async_remote import SamsungTVWSAsyncRemote

async def main(ip):
    tv = SamsungTVWSAsyncRemote(host=ip, port=8002, token_file="token.txt", name="FrameArt", timeout=60)
    await tv.start_listening()
    print("remote OK, token:", "saved" if tv.token else "none")
    await tv.close()
asyncio.run(main(sys.argv[1]))
