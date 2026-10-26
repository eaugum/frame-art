"""Today's weather from Open-Meteo (no key, the same as the home screen), in words for the morning picture."""
import datetime

from . import net

API = "https://api.open-meteo.com/v1/forecast"
WET = 0.2  # mm in an hour that counts as rain

# WMO weather codes: (words, kind). The kind picks the picture's colours.
CODES = {
    0: ("Klart", "clear"), 1: ("Lettskyet", "clear"), 2: ("Delvis skyet", "partly"), 3: ("Overskyet", "cloudy"),
    45: ("Tåke", "fog"), 48: ("Tåke med rim", "fog"),
    51: ("Litt yr", "rain"), 53: ("Yr", "rain"), 55: ("Tett yr", "rain"), 56: ("Underkjølt yr", "rain"),
    57: ("Underkjølt yr", "rain"),
    61: ("Litt regn", "rain"), 63: ("Regn", "rain"), 65: ("Kraftig regn", "rain"), 66: ("Underkjølt regn", "rain"),
    67: ("Underkjølt regn", "rain"),
    71: ("Litt snø", "snow"), 73: ("Snø", "snow"), 75: ("Mye snø", "snow"), 77: ("Snøkorn", "snow"),
    80: ("Regnbyger", "rain"), 81: ("Regnbyger", "rain"), 82: ("Kraftige regnbyger", "rain"),
    85: ("Snøbyger", "snow"), 86: ("Kraftige snøbyger", "snow"),
    95: ("Torden", "thunder"), 96: ("Torden og hagl", "thunder"), 99: ("Torden og hagl", "thunder"),
}
SNOW = {71, 73, 75, 77, 85, 86}


GEOCODING = "https://geocoding-api.open-meteo.com/v1/search"


def place(name):
    """(latitude, longitude, «Lillehammer, Innlandet, Norge») for a place name; «Moss, Norge» narrows it by country
    or county. Raises LookupError when there's none."""
    first, _, rest = name.partition(",")
    found = net.get_json(GEOCODING, {"name": first.strip(), "count": 20, "language": "nb", "format": "json"})
    hits = found.get("results") or []
    rest = rest.strip().lower()
    if rest:
        hits = [h for h in hits if rest in (h.get("country") or "").lower() or rest in (h.get("admin1") or "").lower()]
    if not hits:
        raise LookupError(name)
    h = hits[0]  # the most populous first
    label = ", ".join(x for x in (h.get("name"), h.get("admin1"), h.get("country")) if x)
    return float(h["latitude"]), float(h["longitude"]), label


def today(lat, lon):
    """{high, low, words, kind, wet, sunrise, sunset} for today where the picture hangs."""
    r = net.get_json(API, {"latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 1,
                           "daily": "weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset",
                           "hourly": "precipitation,weather_code"})
    d, h = r["daily"], r["hourly"]
    words, kind = CODES.get(d["weather_code"][0], ("", "cloudy"))
    return {"high": round(d["temperature_2m_max"][0]), "low": round(d["temperature_2m_min"][0]), "words": words,
            "kind": kind, "wet": _wet(h), "sunrise": _clock(d["sunrise"][0]), "sunset": _clock(d["sunset"][0])}


def _wet(h):
    """When it rains or snows in the waking hours: «regn fra kl. 15», «regn det meste av dagen», or ''."""
    hours = [(int(t[11:13]), mm, code) for t, mm, code in zip(h["time"], h["precipitation"], h["weather_code"])]
    wet = [(hour, code) for hour, mm, code in hours if 7 <= hour <= 22 and (mm or 0) >= WET]
    if not wet:
        return ""
    what = "snø" if sum(code in SNOW for _, code in wet) * 2 > len(wet) else "regn"
    if len(wet) >= 10:
        return what + " det meste av dagen"
    first, last = wet[0][0], wet[-1][0]
    if first <= 8:
        return "%s til kl. %d" % (what, last + 1) if last < 20 else what + " det meste av dagen"
    return "%s fra kl. %d" % (what, first)


def _clock(iso):
    return datetime.datetime.fromisoformat(iso).strftime("%H.%M")
