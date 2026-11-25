"""The fake TV answers frameart/tv.py's calls: Art Mode, an upload, choosing a picture, the list and deleting."""
import asyncio
import io
import os
import tempfile
import unittest

from PIL import Image

import fake_tv
from frameart.tv import TV


class FakeTVTest(unittest.TestCase):
    def test_upload_show_delete(self):
        jpeg = io.BytesIO()
        Image.new("RGB", (64, 36), (10, 20, 30)).save(jpeg, "JPEG")

        async def go():
            tv = fake_tv.FakeTV()
            await tv.start()
            try:
                with tempfile.TemporaryDirectory() as d:
                    token = os.path.join(d, "token.txt")
                    with open(token, "w") as f:
                        f.write(fake_tv.TOKEN)
                    async with TV("127.0.0.1", token) as real:
                        self.assertTrue(await real.in_art_mode())
                        content_id = await real.upload(jpeg.getvalue())
                        await real.show(content_id, now=True)
                        self.assertEqual(await real.my_photos(), {content_id})
                        await real.delete([content_id])
                        self.assertEqual(await real.my_photos(), set())
                return tv
            finally:
                await tv.stop()

        tv = asyncio.run(go())
        self.assertEqual(len(tv.uploads), 1)
        self.assertEqual(tv.selected, [{"content_id": "MY_F0001", "show": True}])
        self.assertEqual(tv.deleted, ["MY_F0001"])


if __name__ == "__main__":
    unittest.main()
