"""The pictures we make ourselves (AUG-1447): the morning picture (Morgenbildet) with the date and the weather, and in the
evening a poster of tonight's show from Stasera. Both are 3840x2160 PIL images. The screensaver's pictures (AUG-1494) are
the same poster, for what we watch.
"""
import io
import os

from PIL import Image, ImageDraw, ImageFont

from . import image, net
from .i18n import lang, t

FONT = os.path.join(os.path.dirname(__file__), "fonts", "InterVariable.ttf")
ACCENT = (242, 201, 76)  # Frame TV's yellow

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

def morning_picture(now, weather, extra=None):
    """now: a local datetime. weather: from weather.from_ha(), or None without it. extra: what else
    the day has (today.py): names, events [(time, text)], shows [text] and power ({hourly, cheap, dear, hours,
    lines}), each left out when empty. Two columns from the top of the screen: the day and the weather on the left,
    the rest on the right."""
    extra = extra or {}
    top, bottom, ink = PALETTES[(weather or {}).get("kind", "cloudy")]
    img = _gradient(top, bottom)
    d = ImageDraw.Draw(img)
    soft = tuple(round(i * 0.72 + b * 0.28) for i, b in zip(ink, bottom))
    x, y = 260, 200

    day, date = t("days")[now.weekday()].capitalize(), t("date", day=now.day, month=t("months")[now.month - 1])
    size = 380
    while size > 240 and d.textlength(date, font=font(size, 300)) > MORNING_LEFT - x:  # "28. september"
        size -= 10
    big = font(size, 300)
    d.text((x, y), day, font=big, fill=ink)
    d.text((x, y + size * 1.1), date, font=big, fill=ink)
    y += round(size * 2.32)
    names = extra.get("names") if lang() == "nb" else ""  # the name days are Norwegian
    d.text((x + 8, y), t("week", n=now.isocalendar()[1]) + (t("name_day", names=names) if names else ""),
           font=font(72, 400), fill=ink)
    y += 150

    if weather:
        d.line((x + 8, y, x + 300, y), fill=soft, width=6)
        y += 70
        temp = font(200, 350)
        d.text((x, y), "%d°" % weather["high"], font=temp, fill=ink)
        w = d.textlength("%d°" % weather["high"], font=temp)
        d.text((x + w + 50, y), "/  %d°" % weather["low"], font=temp, fill=soft)
        y += 270
        words = weather["words"]
        if weather["wet"]:  # "Rain most of the day", not "Rain · rain most of the day"
            wet = weather["kind"] in ("rain", "snow")
            words = weather["wet"].capitalize() if wet else words + " · " + weather["wet"]
        d.text((x, y), words, font=font(100, 400), fill=ink)
        y += 150
        small = font(76, 400)
        if weather.get("temps"):
            d.text((x, y), "    ".join("%02d: %d°" % t for t in weather["temps"]), font=small, fill=ink)
            y += 115
        d.text((x, y), t("sun", rise=weather["sunrise"], set=weather["sunset"]), font=small, fill=soft)
        warn = [w for w in (weather.get("wind"), t("slippery") if weather.get("slippery") else "") if w]
        if warn:
            d.text((x, y + 115), " · ".join(warn), font=font(76, 500), fill=ink)
    _day_column(d, extra, ink, soft, (top, bottom), now)
    return img


MORNING_LEFT = 2250  # where the left column ends; the right one starts after a gap


def _day_column(d, extra, ink, soft, gradient, now):
    """The right-hand column: today's events, what's new in Stasera and the electricity price, with its hours."""
    x, right, y = MORNING_LEFT + 150, image.W - 260, 240
    head, body = font(56, 600), font(80, 400)
    power = extra.get("power") or {}
    parts = [(t("today"), ["%s  %s" % (at, s) if at else s for at, s in extra.get("events") or []]),
             (t("new_in_stasera"), extra.get("shows") or []),
             (t("electricity"), power.get("lines") or [])]
    for n, (heading, lines) in enumerate(parts):
        if not lines or y > image.H - 500:
            continue
        d.text((x, y), heading, font=head, fill=soft)
        y += 100
        if n == 2 and y < image.H - 760:
            y = _prices(d, power, x, right, y, ink, soft, gradient, now)
        for line in lines:
            rows = _wrap(d, line, body, right - x)
            if len(rows) > 2:
                rows = [rows[0], rows[1] + " …"]
            for i, row in enumerate(rows):
                if y > image.H - 300:
                    return
                d.text((x + (50 if i else 0), y), row, font=body, fill=ink)
                y += 105
            y += 8
        y += 90


def _prices(d, power, x, right, y, ink, soft, gradient, now):
    """The day's electricity prices as bars, hour by hour: the cheapest stretch in full ink, the dearest in the soft
    colour, the rest fainter and the hours gone fainter still. Returns the y below it."""
    hourly, height = power["hourly"], 280
    back = tuple(t + (b - t) * (y + height / 2) / image.H for t, b in zip(*gradient))  # behind the bars
    faint = tuple(round(s * 0.45 + b * 0.55) for s, b in zip(soft, back))
    gone = tuple(round(s * 0.15 + b * 0.85) for s, b in zip(soft, back))
    top = max(hourly.values()) or 1
    step = (right - x) / 24
    for h in range(24):
        if h not in hourly:
            continue
        colour = ink if power["cheap"] <= h < power["cheap"] + power["hours"] else \
            soft if power["dear"] <= h < power["dear"] + power["hours"] else gone if h < now.hour else faint
        bar = max(6, round(height * max(hourly[h], 0) / top))
        d.rectangle((round(x + h * step + 4), y + height - bar, round(x + (h + 1) * step - 4), y + height), fill=colour)
    tick = font(48, 400)
    for h in (0, 6, 12, 18):
        d.text((round(x + h * step + 4), y + height + 18), "%02d" % h, font=tick, fill=soft)
    return y + height + 110


# MARK: - Tonight's poster

def poster(item, stasera, heading=None):
    """item: one from Stasera's /tv/tonight or /tv/home, stasera the add-on's; heading: "TONIGHT" when it's None. Raises
    when there's no backdrop to make it from."""
    heading = heading or t("tonight")
    path = item.get("textlessBackdropPath") or item.get("backdropPath")
    if not path:
        raise ValueError("no backdrop")
    img = image.fill(image.open_image(net.get(stasera.image(path), timeout=120)))
    img = _shade(img)
    d = ImageDraw.Draw(img)
    x, bottom = 300, image.H - 300

    lines = []  # under the title, from the top
    if item.get("kind") == "show" and item.get("seasonNumber") is not None:
        ep = t("episode", season=item["seasonNumber"], episode=item["episodeNumber"])
        if item.get("episodeName"):
            ep += "  " + t("quote", text=item["episodeName"])
        lines.append(ep)
    elif item.get("runtime"):
        lines.append(_runtime(item["runtime"]))

    line_font = font(80, 400)
    y = bottom - len(lines) * 110
    for i, text in enumerate(lines):
        d.text((x, y + i * 110), text, font=line_font, fill=(236, 236, 236))

    logo = _logo(stasera, item.get("logoPath"))
    if logo:
        logo.thumbnail((1500, 520), Image.LANCZOS)
        top = y - 80 - logo.height
        img.paste(logo, (x, top), logo)
    else:
        title_font = font(200, 600)
        top = y - 80 - 230
        d.text((x, top), item.get("title") or "", font=title_font, fill=(255, 255, 255))
    d.text((x, top - 150), heading, font=font(64, 600), fill=ACCENT)
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


def _logo(stasera, path):
    if not path:
        return None
    try:
        return Image.open(io.BytesIO(net.get(stasera.image(path)))).convert("RGBA")
    except Exception:
        return None


def _runtime(minutes):
    h, m = divmod(int(minutes), 60)
    return (t("hours_minutes", h=h, m=m) if m else t("hours", h=h)) if h else t("minutes", m=m)


# MARK: - Follow the music (AUG-1495)

def music_picture(cover, title, artist, album):
    """cover: the album's cover, a PIL image. The cover big, on a flat in its own colours, with the song, the artist
    and the album (not when it's the song's own name, as for a single)."""
    colour = _cover_colour(cover)
    top = _toward(colour, 0.38)
    bottom = _toward(colour, 0.24)
    img = _gradient(top, bottom)
    side = 1400
    y = (image.H - side) // 2
    x = 330
    img.paste(cover.convert("RGB").resize((side, side), Image.LANCZOS), (x, y))

    d = ImageDraw.Draw(img)
    ink, soft = (240, 238, 234), tuple(round(240 * 0.62 + b * 0.38) for b in bottom)
    tx, width = x + side + 170, image.W - (x + side + 170) - 280
    title_font, artist_font = font(130, 450), font(84, 400)
    lines = _wrap(d, title, title_font, width)[:3]
    if album and album.lower() != (title or "").lower():
        album = _wrap(d, album, font(64, 400), width)[0]
    else:
        album = ""
    height = len(lines) * 160 + 40 + 100 + (90 if album else 0)
    ty = image.H // 2 - height // 2
    for i, line in enumerate(lines):
        d.text((tx, ty + i * 160), line, font=title_font, fill=ink)
    y = ty + len(lines) * 160 + 40
    d.text((tx, y), _wrap(d, artist, artist_font, width)[0], font=artist_font, fill=ink)
    if album:
        d.text((tx, y + 130), album, font=font(64, 400), fill=soft)
    return img


def _cover_colour(cover):
    """The cover's own colour: of its few main colours, the most common, with a push for the colourful ones."""
    small = cover.convert("RGB").resize((64, 64)).quantize(6)
    pal = small.getpalette()
    best, score = (90, 90, 90), -1
    for count, i in small.getcolors():
        r, g, b = pal[i * 3:i * 3 + 3]
        s = count * (0.25 + (max(r, g, b) - min(r, g, b)) / 255)
        if s > score:
            best, score = (r, g, b), s
    return best


def _toward(colour, light):
    """The colour's hue at about this lightness (0-1): dark enough for light text on any cover."""
    now = (0.299 * colour[0] + 0.587 * colour[1] + 0.114 * colour[2]) / 255
    return tuple(min(255, round(c * light / max(now, 0.05))) for c in colour)


def _wrap(d, text, f, width):
    words, lines = (text or "").split(), [""]
    for w in words:
        line = (lines[-1] + " " + w).strip()
        if d.textlength(line, font=f) <= width or not lines[-1]:
            lines[-1] = line
        else:
            lines.append(w)
    if len(lines) > 3:
        lines[2] = lines[2] + " …"
    return lines
