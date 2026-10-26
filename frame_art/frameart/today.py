"""What else Morgenbildet says about the day: the week and the name day, today's events from Home Assistant's calendars,
what's new in Stasera (an episode or a premiere today) and the electricity price. Each part is left out when its source
doesn't answer or has nothing; none of them holds up the picture.
"""
import datetime
import json
import logging
import os
import urllib.parse

log = logging.getLogger(__name__)

with open(os.path.join(os.path.dirname(__file__), "navnedager.json"), encoding="utf-8") as f:
    NAME_DAYS = json.load(f)  # "10-26" -> ["Amandus", "Amanda"], from scripts/navnedager.py
MAX_EVENTS = 5
MAX_SHOWS = 4
PRICE_HOURS = 2  # the cheapest and the dearest stretch of this many hours, from now to midnight


def names(day):
    """«Amandus og Amanda», or '' (1 January, 29 February and Christmas Day have none)."""
    n = NAME_DAYS.get(day.strftime("%m-%d")) or []
    return " og ".join([", ".join(n[:-1]), n[-1]]) if len(n) > 1 else "".join(n)


def events(ha, calendars, now):
    """[(«09.00» or '', summary)] for today from Home Assistant's calendars, all-day ones first."""
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
                out.append((when.strftime("%H.%M") if when else "", (e.get("summary") or "").strip()))
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
            out.append("Premiere: " + title)
        elif i.get("episodeNumber") == 1 and i.get("seasonNumber") == 1:
            out.append("Seriepremiere: " + title)
        elif i.get("episodeNumber") == 1:
            out.append("Ny sesong: %s, sesong %s" % (title, i.get("seasonNumber")))
        else:
            out.append("Ny episode: %s S%sE%s" % (title, i.get("seasonNumber"), i.get("episodeNumber")))
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



def _money(v, unit):
    """In øre under a krone, else in kroner: «42 øre», «1,85 kr». The unit says whether it's øre or kroner already."""
    ore = v if "øre" in (unit or "").lower() or "ore" in (unit or "").lower() else v * 100
    return "%d øre" % round(ore) if ore < 100 else ("%.2f kr" % (ore / 100)).replace(".", ",")


def power(ha, entity, now):
    """[«Billigst kl. 13–15: 42 øre», «Dyrest kl. 17–19: 1,85 kr»] for the rest of today, or []."""
    try:
        s = ha.state(entity)
    except Exception as e:
        log.info("Morgenbildet: no price from %s (%s: %s)", entity, type(e).__name__, e)
        return []
    a = s.get("attributes") or {}
    hourly = _hourly(a, now)
    starts = [h for h in range(now.hour, 24 - PRICE_HOURS + 1) if all(h + i in hourly for i in range(PRICE_HOURS))]
    if not starts:
        return []
    mean = {h: sum(hourly[h + i] for i in range(PRICE_HOURS)) / PRICE_HOURS for h in starts}
    lo, hi = min(starts, key=mean.get), max(starts, key=mean.get)
    unit = a.get("unit_of_measurement") or a.get("unit") or ""
    return ["Billigst kl. %02d–%02d: %s" % (lo, lo + PRICE_HOURS, _money(mean[lo], unit)),
            "Dyrest kl. %02d–%02d: %s" % (hi, hi + PRICE_HOURS, _money(mean[hi], unit))]
