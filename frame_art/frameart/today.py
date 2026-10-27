"""What else Morgenbildet says about the day: the week and the name day, today's events from Home Assistant's calendars,
what's new in Stasera (an episode or a premiere today) and the electricity price. Each part is left out when its source
doesn't answer or has nothing; none of them holds up the picture.
"""
import datetime
import json
import logging
import os
import urllib.parse

from .i18n import t

log = logging.getLogger(__name__)

with open(os.path.join(os.path.dirname(__file__), "navnedager.json"), encoding="utf-8") as f:
    NAME_DAYS = json.load(f)  # "10-26" -> ["Amandus", "Amanda"], from scripts/navnedager.py
MAX_EVENTS = 5
MAX_SHOWS = 4
PRICE_HOURS = 2  # the cheapest and the dearest stretch of this many hours, from now to midnight


def names(day):
    """"Amandus og Amanda", or '' (1 January, 29 February and Christmas Day have none). Norwegian name days."""
    n = NAME_DAYS.get(day.strftime("%m-%d")) or []
    return " og ".join([", ".join(n[:-1]), n[-1]]) if len(n) > 1 else "".join(n)


def events(ha, calendars, now):
    """[("09.00" or '', summary)] for today from Home Assistant's calendars, all-day ones first."""
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    q = urllib.parse.urlencode({"start": start.isoformat(), "end": (start + datetime.timedelta(days=1)).isoformat()})
    out = []
    for entity in calendars:
        try:
            for e in json.loads(ha.get("/api/calendars/%s?%s" % (entity, q))):
                at = (e.get("start") or {}).get("dateTime")
                when = datetime.datetime.fromisoformat(at).astimezone(now.tzinfo) if at else None
                if when and when.date() != now.date():
                    continue  # began yesterday
                out.append((when.strftime(t("clock")) if when else "", (e.get("summary") or "").strip()))
        except Exception as e:
            log.info("Morgenbildet: no events from %s (%s: %s)", entity, type(e).__name__, e)
    return sorted({o for o in out if o[1]})[:MAX_EVENTS]



def shows(stasera, day):
    """[text] for what's new today in Stasera: a new episode, a season or series premiere, a film's premiere."""
    try:
        items = stasera.upcoming(day.isoformat(), 1)
    except Exception as e:
        log.info("Morgenbildet: nothing from Stasera (%s: %s)", type(e).__name__, e)
        return []
    out = []
    for i in items:
        if i.get("date") != day.isoformat():
            continue
        title = i.get("title") or "?"
        if i.get("kind") == "movie":
            out.append(t("premiere", title=title))
        elif i.get("episodeNumber") == 1 and i.get("seasonNumber") == 1:
            out.append(t("series_premiere", title=title))
        elif i.get("episodeNumber") == 1:
            out.append(t("new_season", title=title, season=i.get("seasonNumber")))
        else:
            out.append(t("new_episode", title=title, season=i.get("seasonNumber"), episode=i.get("episodeNumber")))
    return out[:MAX_SHOWS]


def _hourly(attrs, now):
    """{hour: price} for today, from Nord Pool's raw_today ([{start, value}], hours or quarters) or today ([24])."""
    raw = attrs.get("raw_today")
    hours = {}
    if isinstance(raw, list) and raw:
        for r in raw:
            try:
                at = datetime.datetime.fromisoformat(str(r["start"])).astimezone(now.tzinfo)
                hours.setdefault(at.hour, []).append(float(r["value"]))
            except (KeyError, TypeError, ValueError):
                continue
        return {h: sum(v) / len(v) for h, v in hours.items()}
    today = attrs.get("today")
    if isinstance(today, list) and len(today) >= 24:
        step = len(today) // 24  # 96 quarters or 24 hours
        return {h: sum(today[h * step:(h + 1) * step]) / step for h in range(24)
                if all(isinstance(x, (int, float)) for x in today[h * step:(h + 1) * step])}
    return {}


def _tibber(ha, attrs, now):
    """{hour: price} for today from Tibber (tibber.get_prices, in quarters), for the home the sensor is for."""
    day = now.strftime("%Y-%m-%d")
    r = ha.post("/api/services/tibber/get_prices?return_response",
                {"start": day + " 00:00:00", "end": day + " 23:59:59"})
    homes = (r.get("service_response") or {}).get("prices") or {}
    prices = homes.get(attrs.get("app_nickname")) or next(iter(homes.values()), [])
    hours = {}
    for p in prices:
        at = datetime.datetime.fromisoformat(p["start_time"]).astimezone(now.tzinfo)
        if at.date() == now.date():
            hours.setdefault(at.hour, []).append(float(p["price"]))
    return {h: sum(v) / len(v) for h, v in hours.items()}



def _money(v, unit):
    """The price in the sensor's own currency, not the language's. In Norwegian money (NOK, øre, kr, or no unit), øre
    under a krone, else kroner: "42 øre", "1,85 kr". Another currency is the number with it: "0.25 EUR"."""
    u = (unit or "").lower()
    if not u or "nok" in u or "øre" in u or "ore" in u or u.startswith("kr"):
        ore = v if "øre" in u or "ore" in u else v * 100
        return "%d øre" % round(ore) if ore < 100 else ("%.2f kr" % (ore / 100)).replace(".", t("decimal"))
    return ("%.2f %s" % (v, unit.split("/")[0].strip())).replace(".", t("decimal"))


def power(ha, entity, now):
    """{hourly: {hour: price}, lines: ["Cheapest 13–15: 42 øre", "Dearest 17–19: 1.85 kr"], cheap: hour,
    dear: hour} for the rest of today, or None. The prices are in the sensor (Nord Pool), or from Tibber when it's a
    Tibber sensor."""
    try:
        a = ha.state(entity).get("attributes") or {}
        hourly = _hourly(a, now) or (_tibber(ha, a, now) if "app_nickname" in a else {})
    except Exception as e:
        log.info("Morgenbildet: no price from %s (%s: %s)", entity, type(e).__name__, e)
        return None
    starts = [h for h in range(now.hour, 24 - PRICE_HOURS + 1) if all(h + i in hourly for i in range(PRICE_HOURS))]
    if not starts:
        return None
    mean = {h: sum(hourly[h + i] for i in range(PRICE_HOURS)) / PRICE_HOURS for h in starts}
    lo, hi = min(starts, key=mean.get), max(starts, key=mean.get)
    unit = a.get("unit_of_measurement") or a.get("unit") or ""
    return {"hourly": hourly, "cheap": lo, "dear": hi, "hours": PRICE_HOURS,
            "lines": [t("cheapest", start="%02d" % lo, end="%02d" % (lo + PRICE_HOURS), price=_money(mean[lo], unit)),
                      t("dearest", start="%02d" % hi, end="%02d" % (hi + PRICE_HOURS), price=_money(mean[hi], unit))]}
