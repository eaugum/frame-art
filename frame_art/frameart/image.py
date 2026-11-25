"""Makes any picture a 3840x2160 JPEG for The Frame."""
import ctypes
import io

from PIL import Image, ImageOps

from . import limits

W, H = 3840, 2160
# What the sources hand us: the folder's extensions (sources.Folder.EXT) and what the services serve. Not the rarer
# decoders (EPS, PSD, JPEG 2000...), which no source needs
FORMATS = ("JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF")
# Pillow's own warning level, as the limit: a museum's original of 8000x6000 is 48 MP; 90 MP is about 360 MB decoded
MAX_PIXELS = 90_000_000
BYTES = {"1": 1, "L": 1, "P": 1, "I;16": 2, "I;16L": 2, "I;16B": 2, "I;16N": 2}  # per pixel in Pillow; else 4

try:  # glibc keeps what a thread frees for that thread: a big picture freed in each of the threads would stay taken.
    ctypes.CDLL("libc.so.6").mallopt(-3, 2 ** 20)  # M_MMAP_THRESHOLD: blocks over 1 MB go back when they're freed
except (OSError, AttributeError):
    pass  # not glibc

# Only pictures this close to 16:9 are used, cropped to fill the screen (from 3:2 to a little wider than 16:9)
CROP_MIN, CROP_MAX = 1.45, 2.0
MIN_WIDTH = 1920  # museum pictures smaller than this look soft on a 4K wall
THUMB = 480  # the add-on page's grid


def _turned(img):
    """The header says it's stored turned (phone photos). Read without decoding: a PNG's EXIF after its data isn't."""
    if img.format == "PNG" and "exif" not in img.info:
        return False
    return img.getexif().get(0x0112, 1) != 1


def open_image(data, draft=None, mode="RGB"):
    """The picture, decoded once its job has the memory for it (limits.hold), and closed when the job ends. Another
    format, or more than MAX_PIXELS or limits.MEMORY, raises from the header, before it's decoded."""
    img = Image.open(io.BytesIO(data), formats=FORMATS)
    if img.width * img.height > MAX_PIXELS:
        raise Image.DecompressionBombError("%dx%d is more than %d pixels" % (img.width, img.height, MAX_PIXELS))
    if draft:
        img.draft("RGB", (draft, draft))  # a JPEG decodes at a fraction of its size: fast for a thumbnail
    pixels = img.width * img.height
    decoded = pixels * BYTES.get(img.mode, 4)
    turned = _turned(img)
    converted = 0 if img.mode == mode else pixels * 4
    taken = decoded + max(decoded if turned else 0, converted)  # turning makes a copy, then converting does
    if taken > limits.MEMORY:
        raise limits.TooBig("%d MB decoded is more than %d MB" % (taken >> 20, limits.MEMORY >> 20))
    limits.hold(taken)
    limits.keep(img)
    img.load()
    if turned:
        ImageOps.exif_transpose(img, in_place=True)
    if converted:
        img = img.convert(mode)
        limits.keep(img)
    return img


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
    """A small JPEG of img, which is made small itself: it's the caller's own, and a copy of a big one is costly."""
    img.thumbnail((THUMB, THUMB), Image.LANCZOS)
    return to_jpeg(img if img.mode == "RGB" else img.convert("RGB"), 80)
