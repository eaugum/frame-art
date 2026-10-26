"""Makes any picture a 3840x2160 JPEG for The Frame."""
import io

from PIL import Image, ImageOps

W, H = 3840, 2160

# Only pictures this close to 16:9 are used, cropped to fill the screen (from 3:2 to a little wider than 16:9)
CROP_MIN, CROP_MAX = 1.45, 2.0
MIN_WIDTH = 1920  # museum pictures smaller than this look soft on a 4K wall
THUMB = 480  # the add-on page's grid


def open_image(data, draft=None):
    img = Image.open(io.BytesIO(data))
    if draft:
        img.draft("RGB", (draft, draft))  # a JPEG decodes at a fraction of its size: fast for a thumbnail
    img = ImageOps.exif_transpose(img)  # phone photos are stored sideways with a tag
    return img.convert("RGB")


def croppable(width, height):
    return width > 0 and height > 0 and CROP_MIN <= width / height <= CROP_MAX


def big_enough(width, height):
    return croppable(width, height) and width >= MIN_WIDTH


def fill(img):
    """Crops to 16:9 around the centre."""
    return ImageOps.fit(img, (W, H), Image.LANCZOS, centering=(0.5, 0.5))


def to_jpeg(img, quality=90):
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality, optimize=True)
    return out.getvalue()


def thumbnail(img):
    img = img.copy()
    img.thumbnail((THUMB, THUMB), Image.LANCZOS)
    return to_jpeg(img.convert("RGB"), 80)
