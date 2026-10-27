"""Today's weather for the morning picture, from a weather entity in Home Assistant (weather.forecast_home: met.no,
as Yr) and sun.sun, in words."""
import datetime

from .i18n import t

WET = 0.2  # mm in an hour that counts as rain
TEMP_HOURS = (8, 12, 16, 20)  # the temperature through the day
WINDY = 8.0  # m/s: from frisk bris, the wind is worth a line
# The Beaufort scale from m/s, from hurricane down to fresh breeze; the names are t("winds") in the same order
WINDS = (32.7, 28.5, 24.5, 20.8, 17.2, 13.9, 10.8, WINDY)
SLIPPERY = (-3.0, 1.5)  # °C: precipitation in the morning at these temperatures freezes on the roads

# Home Assistant's conditions (met.no and others) -> the kind, which picks the colours; the words are t("conditions")
CONDITIONS = {
    "sunny": "clear", "clear-night": "clear", "partlycloudy": "partly", "cloudy": "cloudy", "fog": "fog",
    "rainy": "rain", "pouring": "rain", "snowy": "snow", "snowy-rainy": "rain", "hail": "rain",
    "lightning": "thunder", "lightning-rainy": "thunder", "windy": "cloudy", "windy-variant": "cloudy",
    "exceptional": "cloudy",
}


def from_ha(ha, entity, now):
    """{high, low, words, kind, wet, sunrise, sunset, temps, wind, slippery} for today. The kind picks the picture's
    colours; temps is [(hour, °)], wind a line or '' and slippery whether the roads may be icy this morning."""
    def forecast(kind):
        r = ha.post("/api/services/weather/get_forecasts?return_response", {"entity_id": entity, "type": kind})
        return [dict(f, at=datetime.datetime.fromisoformat(f["datetime"]).astimezone(now.tzinfo))
                for f in r["service_response"][entity]["forecast"]]
    day = next(f for f in forecast("daily") if f["at"].date() == now.date())
    hourly = [f for f in forecast("hourly") if f["at"].date() == now.date()]
    hours = [(f["at"].hour, f.get("precipitation"), f.get("condition") == "snowy") for f in hourly]
    state = ha.state(entity).get("attributes") or {}
    per_s = 1 / 3.6 if state.get("wind_speed_unit") == "km/h" else 1
    words, kind = t("conditions").get(day.get("condition"), ""), CONDITIONS.get(day.get("condition"), "cloudy")
    sun = ha.state("sun.sun").get("attributes") or {}

    def clock(k):  # the next sunrise or sunset: today's, or tomorrow's (a few minutes off) once it's passed
        return datetime.datetime.fromisoformat(sun[k]).astimezone(now.tzinfo).strftime(t("clock")) if sun.get(k) else "–"
    return {"high": round(day["temperature"]), "low": round(day.get("templow", day["temperature"])), "words": words,
            "kind": kind, "wet": _wet_hours(hours), "sunrise": clock("next_rising"), "sunset": clock("next_setting"),
            "temps": [(f["at"].hour, round(f["temperature"])) for f in hourly
                      if f["at"].hour in TEMP_HOURS and f.get("temperature") is not None],
            "wind": _wind([f for f in hourly if 7 <= f["at"].hour <= 22], per_s),
            "slippery": any(_freezing(f) for f in hourly if 5 <= f["at"].hour <= 11)}


def _freezing(f):
    """Precipitation at a temperature that freezes on the roads."""
    t = f.get("temperature")
    return t is not None and SLIPPERY[0] <= t <= SLIPPERY[1] and (f.get("precipitation") or 0) > 0


def _wind(hours, per_s):
    """"Strong breeze from the southwest, gusts 18 m/s" for the windiest hour of the day, or '' when it's under WINDY."""
    if not hours:
        return ""
    top = max(hours, key=lambda f: f.get("wind_speed") or 0)
    speed = (top.get("wind_speed") or 0) * per_s
    n = next((n for n, least in enumerate(WINDS) if speed >= least), None)
    if n is None:
        return ""
    name = t("winds")[n]
    gust = max((f.get("wind_gust_speed") or 0) for f in hours) * per_s
    bearing = top.get("wind_bearing")
    if isinstance(bearing, (int, float)):
        name = t("wind_from", wind=name, direction=t("directions")[round(bearing / 45) % 8])
    return name[:1].upper() + name[1:] + (t("gusts", n=round(gust)) if gust > speed else "")


def _wet_hours(hours):
    """When it rains or snows in the waking hours, from [(hour, mm, snow)]: "rain from 15:00", "rain most of the day",
    or ''."""
    wet = [(hour, snow) for hour, mm, snow in hours if 7 <= hour <= 22 and (mm or 0) >= WET]
    if not wet:
        return ""
    what = t("snow") if sum(snow for _, snow in wet) * 2 > len(wet) else t("rain")
    if len(wet) >= 10:
        return t("wet_all_day", what=what)
    first, last = wet[0][0], wet[-1][0]
    if first <= 8:
        return t("wet_until", what=what, hour=last + 1) if last < 20 else t("wet_all_day", what=what)
    return t("wet_from", what=what, hour=first)
