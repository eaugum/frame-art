"""Today's weather for the morning picture, from a weather entity in Home Assistant (weather.forecast_home: met.no,
as Yr) and sun.sun, in words."""
import datetime

WET = 0.2  # mm in an hour that counts as rain
TEMP_HOURS = (8, 12, 16, 20)  # the temperature through the day
WINDY = 8.0  # m/s: from frisk bris, the wind is worth a line
# The Beaufort scale's Norwegian names, from m/s
WINDS = ((32.7, "orkan"), (28.5, "sterk storm"), (24.5, "full storm"), (20.8, "liten storm"), (17.2, "sterk kuling"),
         (13.9, "stiv kuling"), (10.8, "liten kuling"), (WINDY, "frisk bris"))
DIRECTIONS = ("nord", "nordøst", "øst", "sørøst", "sør", "sørvest", "vest", "nordvest")
SLIPPERY = (-3.0, 1.5)  # °C: nedbør in the morning at these temperatures freezes on the roads

# Home Assistant's conditions (met.no and others): (words, kind)
CONDITIONS = {
    "sunny": ("Klart", "clear"), "clear-night": ("Klart", "clear"), "partlycloudy": ("Delvis skyet", "partly"),
    "cloudy": ("Overskyet", "cloudy"), "fog": ("Tåke", "fog"), "rainy": ("Regn", "rain"),
    "pouring": ("Kraftig regn", "rain"), "snowy": ("Snø", "snow"), "snowy-rainy": ("Sludd", "rain"),
    "hail": ("Hagl", "rain"), "lightning": ("Torden", "thunder"), "lightning-rainy": ("Torden og regn", "thunder"),
    "windy": ("Vind", "cloudy"), "windy-variant": ("Vind og skyer", "cloudy"), "exceptional": ("Uvanlig vær", "cloudy"),
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
    words, kind = CONDITIONS.get(day.get("condition"), ("", "cloudy"))
    sun = ha.state("sun.sun").get("attributes") or {}

    def clock(k):  # the next sunrise or sunset: today's, or tomorrow's (a few minutes off) once it's passed
        return datetime.datetime.fromisoformat(sun[k]).astimezone(now.tzinfo).strftime("%H.%M") if sun.get(k) else "–"
    return {"high": round(day["temperature"]), "low": round(day.get("templow", day["temperature"])), "words": words,
            "kind": kind, "wet": _wet_hours(hours), "sunrise": clock("next_rising"), "sunset": clock("next_setting"),
            "temps": [(f["at"].hour, round(f["temperature"])) for f in hourly
                      if f["at"].hour in TEMP_HOURS and f.get("temperature") is not None],
            "wind": _wind([f for f in hourly if 7 <= f["at"].hour <= 22], per_s),
            "slippery": any(_freezing(f) for f in hourly if 5 <= f["at"].hour <= 11)}


def _freezing(f):
    """Nedbør at a temperature that freezes on the roads."""
    t = f.get("temperature")
    return t is not None and SLIPPERY[0] <= t <= SLIPPERY[1] and (f.get("precipitation") or 0) > 0


def _wind(hours, per_s):
    """«Liten kuling fra sørvest, kast 18 m/s» for the windiest hour of the day, or '' when it's under WINDY."""
    if not hours:
        return ""
    top = max(hours, key=lambda f: f.get("wind_speed") or 0)
    speed = (top.get("wind_speed") or 0) * per_s
    name = next((n for least, n in WINDS if speed >= least), None)
    if not name:
        return ""
    gust = max((f.get("wind_gust_speed") or 0) for f in hours) * per_s
    bearing = top.get("wind_bearing")
    where = " fra " + DIRECTIONS[round(bearing / 45) % 8] if isinstance(bearing, (int, float)) else ""
    return name.capitalize() + where + (", kast %d m/s" % round(gust) if gust > speed else "")


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
