"""Today's weather for the morning picture, from a weather entity in Home Assistant (weather.forecast_home: met.no,
as Yr) and sun.sun, in words."""
import datetime

WET = 0.2  # mm in an hour that counts as rain

# Home Assistant's conditions (met.no and others): (words, kind)
CONDITIONS = {
    "sunny": ("Klart", "clear"), "clear-night": ("Klart", "clear"), "partlycloudy": ("Delvis skyet", "partly"),
    "cloudy": ("Overskyet", "cloudy"), "fog": ("Tåke", "fog"), "rainy": ("Regn", "rain"),
    "pouring": ("Kraftig regn", "rain"), "snowy": ("Snø", "snow"), "snowy-rainy": ("Sludd", "rain"),
    "hail": ("Hagl", "rain"), "lightning": ("Torden", "thunder"), "lightning-rainy": ("Torden og regn", "thunder"),
    "windy": ("Vind", "cloudy"), "windy-variant": ("Vind og skyer", "cloudy"), "exceptional": ("Uvanlig vær", "cloudy"),
}


def from_ha(ha, entity, now):
    """{high, low, words, kind, wet, sunrise, sunset} for today. The kind picks the picture's colours."""
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
