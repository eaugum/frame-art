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


# Home Assistant's conditions (met.no and others): (words, kind)
CONDITIONS = {
    "sunny": ("Klart", "clear"), "clear-night": ("Klart", "clear"), "partlycloudy": ("Delvis skyet", "partly"),
    "cloudy": ("Overskyet", "cloudy"), "fog": ("Tåke", "fog"), "rainy": ("Regn", "rain"),
    "pouring": ("Kraftig regn", "rain"), "snowy": ("Snø", "snow"), "snowy-rainy": ("Sludd", "rain"),
    "hail": ("Hagl", "rain"), "lightning": ("Torden", "thunder"), "lightning-rainy": ("Torden og regn", "thunder"),
    "windy": ("Vind", "cloudy"), "windy-variant": ("Vind og skyer", "cloudy"), "exceptional": ("Uvanlig vær", "cloudy"),
}


def from_ha(ha, entity, now):
    """The same as today(), from a weather entity in Home Assistant (weather.forecast_home: met.no) and sun.sun."""
    def forecast(kind):
        r = ha.post("/api/services/weather/get_forecasts?return_response", {"entity_id": entity, "type": kind})
        return [dict(f, at=datetime.datetime.fromisoformat(f["datetime"]).astimezone(now.tzinfo))
                for f in r["service_response"][entity]["forecast"]]
    day = next(f for f in forecast("daily") if f["at"].date() == now.date())
    hours = [(f["at"].hour, f.get("precipitation"), f.get("condition") == "snowy")
             for f in forecast("hourly") if f["at"].date() == now.date()]
    words, kind = CONDITIONS.get(day.get("condition"), ("", "cloudy"))
    sun = ha.state("sun.sun").get("attributes") or {}

    def clock(k):  # the next sunrise or sunset: today's, or tomorrow's (a few minutes off) once it's passed
        return datetime.datetime.fromisoformat(sun[k]).astimezone(now.tzinfo).strftime("%H.%M") if sun.get(k) else "–"
    return {"high": round(day["temperature"]), "low": round(day.get("templow", day["temperature"])), "words": words,
            "kind": kind, "wet": _wet_hours(hours), "sunrise": clock("next_rising"), "sunset": clock("next_setting")}


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
    hours = [(int(t[11:13]), mm, code in SNOW) for t, mm, code in zip(h["time"], h["precipitation"], h["weather_code"])]
    return _wet_hours(hours)


def _wet_hours(hours):
    """When it rains or snows in the waking hours, from [(hour, mm, snow)]: «regn fra kl. 15», «regn det meste av
    dagen», or ''."""
    wet = [(hour, snow) for hour, mm, snow in hours if 7 <= hour <= 22 and (mm or 0) >= WET]
    if not wet:
        return ""
    what = "snø" if sum(snow for _, snow in wet) * 2 > len(wet) else "regn"
    if len(wet) >= 10:
        return what + " det meste av dagen"
    first, last = wet[0][0], wet[-1][0]
    if first <= 8:
        return "%s til kl. %d" % (what, last + 1) if last < 20 else what + " det meste av dagen"
    return "%s fra kl. %d" % (what, first)


def _clock(iso):
    return datetime.datetime.fromisoformat(iso).strftime("%H.%M")
