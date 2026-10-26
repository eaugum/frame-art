"""The pictures we make ourselves (AUG-1447): the morning picture (Morgenbildet) with the date and the weather, and in the
evening a poster of tonight's show from Stasera. Both are 3840x2160 PIL images.
"""
import io
import os

from PIL import Image, ImageDraw, ImageFont

from . import image, net

FONT = os.path.join(os.path.dirname(__file__), "fonts", "InterVariable.ttf")
TMDB = "https://image.tmdb.org/t/p/"
ACCENT = (242, 201, 76)  # Frame TV's yellow

DAYS = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]
MONTHS = ["januar", "februar", "mars", "april", "mai", "juni", "juli", "august", "september", "oktober", "november",
          "desember"]

# Calm colours for the weather: (top, bottom, text)
PALETTES = {
    "clear": ((222, 205, 172), (198, 172, 130), (46, 38, 28)),
    "partly": ((196, 207, 210), (160, 176, 182), (30, 40, 46)),
    "cloudy": ((176, 179, 178), (140, 145, 146), (32, 34, 36)),
    "fog": ((206, 205, 197), (178, 178, 170), (44, 44, 40)),
    "rain": ((96, 110, 122), (66, 78, 90), (236, 240, 242)),
    "snow": ((226, 232, 235), (196, 206, 212), (34, 46, 56)),
    "thunder": ((70, 74, 88), (40, 43, 54), (232, 232, 238)),
}


def font(size, weight=400, opsz=32):
    f = ImageFont.truetype(FONT, size)
    f.set_variation_by_axes([opsz, weight])
    return f


def _gradient(top, bottom):
    """A vertical gradient with a little grain, so a 4K wall shows no bands."""
    col = Image.new("RGB", (1, image.H))
    for y in range(image.H):
        t = y / (image.H - 1)
        col.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    img = col.resize((image.W, image.H))
    noise = Image.effect_noise((image.W // 2, image.H // 2), 18).resize((image.W, image.H)).convert("RGB")
    return Image.blend(img, noise, 0.035)


# MARK: - The morning picture

def morning_picture(now, weather):
    """now: a local datetime. weather: from weather.today(), or None when Open-Meteo didn't answer."""
    top, bottom, ink = PALETTES[(weather or {}).get("kind", "cloudy")]
    img = _gradient(top, bottom)
    d = ImageDraw.Draw(img)
    soft = tuple(round(i * 0.72 + b * 0.28) for i, b in zip(ink, bottom))
    x = 330

    big = font(300, 300)
    d.text((x, 560), DAYS[now.weekday()].capitalize(), font=big, fill=ink)
    d.text((x, 900), "%d. %s" % (now.day, MONTHS[now.month - 1]), font=big, fill=ink)

    if weather:
        d.line((x + 8, 1380, x + 260, 1380), fill=soft, width=5)
        temp = font(150, 350)
        d.text((x, 1450), "%d°" % weather["high"], font=temp, fill=ink)
        w = d.textlength("%d°" % weather["high"], font=temp)
        d.text((x + w + 40, 1450), "/  %d°" % weather["low"], font=temp, fill=soft)
        words = weather["words"]
        if weather["wet"]:  # «Regn det meste av dagen», not «Regn · regn det meste av dagen»
            wet = weather["kind"] in ("rain", "snow")
            words = weather["wet"].capitalize() if wet else words + " · " + weather["wet"]
        d.text((x, 1660), words, font=font(84, 400), fill=ink)
        d.text((x, 1790), "Sola opp %s · ned %s" % (weather["sunrise"], weather["sunset"]), font=font(64, 400),
               fill=soft)
    return img


# MARK: - Tonight's poster

def poster(item):
    """item: one from Stasera's /tv/tonight. Raises when there's no backdrop to make it from."""
    path = item.get("textlessBackdropPath") or item.get("backdropPath")
    if not path:
        raise ValueError("no backdrop")
    img = image.fill(image.open_image(net.get(TMDB + "original" + path, timeout=120)))
    img = _shade(img)
    d = ImageDraw.Draw(img)
    x, bottom = 300, image.H - 300

    lines = []  # under the title, from the top
    if item.get("kind") == "show" and item.get("seasonNumber") is not None:
        ep = "Sesong %d, episode %d" % (item["seasonNumber"], item["episodeNumber"])
        if item.get("episodeName"):
            ep += "  «%s»" % item["episodeName"]
        lines.append(ep)
    elif item.get("runtime"):
        lines.append(_runtime(item["runtime"]))

    line_font = font(80, 400)
    y = bottom - len(lines) * 110
    for i, text in enumerate(lines):
        d.text((x, y + i * 110), text, font=line_font, fill=(236, 236, 236))

    logo = _logo(item.get("logoPath"))
    if logo:
        logo.thumbnail((1500, 520), Image.LANCZOS)
        top = y - 80 - logo.height
        img.paste(logo, (x, top), logo)
    else:
        title_font = font(200, 600)
        top = y - 80 - 230
        d.text((x, top), item.get("title") or "", font=title_font, fill=(255, 255, 255))
    d.text((x, top - 150), "I KVELD", font=font(64, 600), fill=ACCENT)
    return img


def _shade(img):
    """Darker to the left and at the bottom, where the text goes."""
    small = Image.new("L", (96, 54))
    sp = small.load()
    for yy in range(54):
        for xx in range(96):
            left = max(0.0, 1 - xx / 60) ** 1.4
            low = max(0.0, (yy - 20) / 34) ** 1.6
            sp[xx, yy] = round(255 * min(0.86, 0.18 + 0.62 * left + 0.4 * low))
    mask = small.resize((image.W, image.H), Image.BICUBIC)
    return Image.composite(Image.new("RGB", img.size, (8, 8, 10)), img, mask)


def _logo(path):
    if not path:
        return None
    try:
        return Image.open(io.BytesIO(net.get(TMDB + "original" + path))).convert("RGBA")
    except Exception:
        return None


def _runtime(minutes):
    h, m = divmod(int(minutes), 60)
    return ("%d t %d min" % (h, m) if m else "%d t" % h) if h else "%d min" % m
