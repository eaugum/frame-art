"""Makes any picture a 3840x2160 JPEG for The Frame."""
import io

from PIL import Image, ImageFilter, ImageOps

W, H = 3840, 2160

# Paintings this close to 16:9 are cropped; the rest are skipped (museums) or shown whole on a blurred copy (folder).
CROP_MIN, CROP_MAX = 1.3, 2.1
MIN_WIDTH = 1920  # museum pictures smaller than this look soft on a 4K wall


def open_image(data):
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)  # phone photos are stored sideways with a tag
    return img.convert("RGB")


def croppable(width, height):
    return width > 0 and height > 0 and CROP_MIN <= width / height <= CROP_MAX


def big_enough(width, height):
    return croppable(width, height) and width >= MIN_WIDTH


def usable(width, height, whole=False):
    """big_enough for a source that crops; for one shown whole (any shape), not enlarged more than twice."""
    if not whole:
        return big_enough(width, height)
    return width > 0 and height > 0 and min(W / width, H / height) <= 2


def fill(img):
    """Crops to 16:9 around the centre."""
    return ImageOps.fit(img, (W, H), Image.LANCZOS, centering=(0.5, 0.5))


def fit_on_blur(img):
    """The whole picture, on a darkened, blurred copy of itself."""
    back = fill(img).resize((W // 8, H // 8), Image.BILINEAR).filter(ImageFilter.GaussianBlur(6))
    back = back.resize((W, H), Image.BILINEAR).point(lambda v: int(v * 0.55))
    front = ImageOps.contain(img, (W, H), Image.LANCZOS)
    back.paste(front, ((W - front.width) // 2, (H - front.height) // 2))
    return back


def to_jpeg(img):
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90, optimize=True)
    return out.getvalue()
