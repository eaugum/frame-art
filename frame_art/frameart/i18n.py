"""What Frame Art puts on the wall, in English or Norwegian (AUG-1501): the morning picture and the posters.

The language is `language` in the options: en, nb, or auto (the default), which follows Home Assistant's system
language (GET /api/config). Any other language gives English. keep() looks it up in the background, since Home
Assistant may still be starting when the add-on does. The add-on's page and its device in Home Assistant are always
in English.
"""
import asyncio
import json
import logging

log = logging.getLogger(__name__)

LANGUAGES = ("en", "nb")
LOOK_SECONDS = 600  # Home Assistant's language is looked at again this often (every 30 s until it answers)

STRINGS = {
    "en": {
        # The morning picture
        "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "months": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                   "November", "December"],
        "date": "{month} {day}",
        "week": "Week {n}",
        "name_day": " · Name day: {names}",
        "clock": "%H:%M",
        "sun": "Sunrise {rise} · sunset {set}",
        "slippery": "Risk of icy roads",
        "today": "TODAY",
        "new_in_stasera": "NEW IN STASERA",
        "electricity": "ELECTRICITY",
        "cheapest": "Cheapest {start}–{end}: {price}",
        "dearest": "Dearest {start}–{end}: {price}",
        "premiere": "Premiere: {title}",
        "series_premiere": "Series premiere: {title}",
        "new_season": "New season: {title}, season {season}",
        "new_episode": "New episode: {title} S{season}E{episode}",
        "and": " and ",
        "decimal": ".",
        # The weather
        "conditions": {"sunny": "Clear", "clear-night": "Clear", "partlycloudy": "Partly cloudy", "cloudy": "Cloudy",
                       "fog": "Fog", "rainy": "Rain", "pouring": "Heavy rain", "snowy": "Snow", "snowy-rainy": "Sleet",
                       "hail": "Hail", "lightning": "Thunder", "lightning-rainy": "Thunder and rain",
                       "windy": "Wind", "windy-variant": "Wind and clouds", "exceptional": "Unusual weather"},
        "winds": ["hurricane", "violent storm", "storm", "severe gale", "gale", "near gale", "strong breeze",
                  "fresh breeze"],
        "directions": ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"],
        "wind_from": "{wind} from the {direction}",
        "gusts": ", gusts {n} m/s",
        "rain": "rain",
        "snow": "snow",
        "wet_all_day": "{what} most of the day",
        "wet_until": "{what} until {hour}:00",
        "wet_from": "{what} from {hour}:00",
        # Posters
        "tonight": "TONIGHT",
        "watching": "WATCHING",
        "want_to_start": "WANT TO START",
        "episode": "Season {season}, episode {episode}",
        "quote": "“{text}”",
        "hours_minutes": "{h} h {m} min",
        "hours": "{h} h",
        "minutes": "{m} min",
    },
    "nb": {
        "days": ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"],
        "months": ["januar", "februar", "mars", "april", "mai", "juni", "juli", "august", "september", "oktober",
                   "november", "desember"],
        "date": "{day}. {month}",
        "week": "Uke {n}",
        "name_day": " · Navnedag: {names}",
        "clock": "%H.%M",
        "sun": "Sola opp {rise} · ned {set}",
        "slippery": "Fare for glatte veier",
        "today": "I DAG",
        "new_in_stasera": "NYTT I STASERA",
        "electricity": "STRØM",
        "cheapest": "Billigst kl. {start}–{end}: {price}",
        "dearest": "Dyrest kl. {start}–{end}: {price}",
        "premiere": "Premiere: {title}",
        "series_premiere": "Seriepremiere: {title}",
        "new_season": "Ny sesong: {title}, sesong {season}",
        "new_episode": "Ny episode: {title} S{season}E{episode}",
        "and": " og ",
        "decimal": ",",
        "conditions": {"sunny": "Klart", "clear-night": "Klart", "partlycloudy": "Delvis skyet", "cloudy": "Overskyet",
                       "fog": "Tåke", "rainy": "Regn", "pouring": "Kraftig regn", "snowy": "Snø", "snowy-rainy": "Sludd",
                       "hail": "Hagl", "lightning": "Torden", "lightning-rainy": "Torden og regn",
                       "windy": "Vind", "windy-variant": "Vind og skyer", "exceptional": "Uvanlig vær"},
        "winds": ["orkan", "sterk storm", "full storm", "liten storm", "sterk kuling", "stiv kuling", "liten kuling",
                  "frisk bris"],
        "directions": ["nord", "nordøst", "øst", "sørøst", "sør", "sørvest", "vest", "nordvest"],
        "wind_from": "{wind} fra {direction}",
        "gusts": ", kast {n} m/s",
        "rain": "regn",
        "snow": "snø",
        "wet_all_day": "{what} det meste av dagen",
        "wet_until": "{what} til kl. {hour}",
        "wet_from": "{what} fra kl. {hour}",
        "tonight": "I KVELD",
        "watching": "SER PÅ",
        "want_to_start": "VIL BEGYNNE PÅ",
        "episode": "Sesong {season}, episode {episode}",
        "quote": "«{text}»",
        "hours_minutes": "{h} t {m} min",
        "hours": "{h} t",
        "minutes": "{m} min",
    },
}

# The add-on's page, always in English: put into it as JSON when it's served (api.py)
PAGE = {
    "locale": "en-GB",
    "new_picture": "New picture",
    "show_morning": "Show the morning picture",
    "show_tonight": "Show tonight's show",
    "pictures": "Pictures",
    "recently_shown": "Recently shown",
    "random": "Random",
    "show_others": "Show others",
    "close": "Close",
    "settings": "Settings",
    "interval": "Change the picture every",
    "keep": "Pictures left on the TV",
    "keep_note": "Under “My Photos” in Art Mode; the older ones are deleted",
    "morning": "Morning picture",
    "morning_note": "Date, weather, week and what's new in Stasera; events and electricity from the options in HA",
    "tv_on": "Turn the TV on first",
    "tv_on_note": "Through Home Assistant, when it's off",
    "tv_on_missing": "Set tv_entity in the add-on's configuration",
    "tonight": "Tonight's show",
    "tonight_note": "From “Tonight” in Stasera",
    "screensaver": "Screensaver",
    "screensaver_note": "Frame TV goes to Art Mode when it's left alone",
    "screensaver_stasera": "The screensaver with the Stasera pictures",
    "screensaver_stasera_note": "With the title; otherwise the usual rotation",
    "music": "Follow the music",
    "music_note": "The album cover while music is playing",
    "home_only": "Only when someone is home",
    "home_only_note": "Follow the music, and turning the TV on; from {entity}",
    "home_only_missing": "Set home_entity in the add-on's configuration",
    "link": "Link",
    "unlink": "Unlink",
    "tv_off": "The TV is off. Turn it on?",
    "tv_off_note": "It takes half a minute before the picture comes.",
    "turn_on": "Turn on",
    "cancel": "Cancel",
    "today_at": "today at {time}",
    "tomorrow_at": "tomorrow at {time}",
    "reading": "reading …",
    "n_pictures": "{n} pictures",
    "no_pictures": "no pictures",
    "not_changed": "Not changed yet",
    "changed_at": "changed {time}",
    "fixed": "Fixed picture",
    "fixed_until": "stays until {when} ",
    "resume": "Resume the rotation now",
    "coming": "coming right up",
    "saver": "Screensaver",
    "saver_words": "the Stasera pictures, a new one every {n} min",
    "rotation": "Rotation",
    "rotation_words": "a new picture every {n} min from {sources}",
    "source_one": "{n} source",
    "source_other": "{n} sources",
    "next_at": " · next {time}",
    "standing": "standing still: no sources are ticked",
    "choose": "Choose picture",
    "sum": "{on} of {total} sources · {pictures} pictures",
    "none_ticked": "No sources are ticked, so the picture doesn't change.",
    "reading_sources": "Reading the sources that haven't been read before …",
    "stasera_off": "Off: stasera_url is missing in the add-on's options.",
    "stasera_linked": "Linked. Tonight's show comes from “Tonight”.",
    "stasera_approve": "Approve the code {code} in {stasera}.",
    "stasera_unlinked": "Not linked.",
    "stasera_no_answer": "No answer from Stasera.",
    "turning_on": "Turning the TV on … {doing}",
    "done": "Done.",
    "failed": "Didn't work: {error}",
    "unknown_error": "unknown error",
    "no_answer": "No answer.",
    "saved": "Saved",
    "not_saved": "Not saved: {error}",
    "couldnt_save": "Couldn't save.",
    "showing_until": "Showing the picture and keeping it until the morning picture …",
    "fetching": "Fetching …",
    "gallery_off": "None of the sources in {name} are ticked.",
    "gallery_reading": "Reading {names} (the first time takes a while). Press “Show others” in a moment. ",
    "gallery_empty": "No pictures here. ",
    "gallery_hint": "A picture you press stays until the next morning picture.",
    "fetching_new": "Fetching a new picture and sending it to the TV …",
    "making_morning": "Making the morning picture …",
    "making_tonight": "Making the poster for tonight's show …",
}

_chosen = "auto"  # the option
_lang = "en"  # what's in use


def normalize(code):
    """'nb', 'no', 'nn' and 'nb-NO' are Norwegian; English otherwise."""
    code = (code or "").lower().replace("_", "-").split("-")[0]
    return "nb" if code in ("nb", "no", "nn") else "en"


def setup(cfg):
    """The language from the options; with auto, English until keep() has asked Home Assistant."""
    global _chosen, _lang
    _chosen = (cfg.get("language") or "auto").strip().lower()
    if _chosen != "auto":
        _lang = normalize(_chosen)


def lang():
    return _lang


def ask(ha):
    """Home Assistant's language now (raises when it doesn't answer); the option when it isn't auto."""
    global _lang
    if _chosen != "auto":
        return _lang
    was = _lang
    _lang = normalize(json.loads(ha.get("/api/config")).get("language"))
    if _lang != was:
        log.info("language: %s (Home Assistant's)", _lang)
    return _lang


async def keep(ha):
    """With auto: Home Assistant's language, looked at now and then (it can change, and it may not answer at first)."""
    if _chosen != "auto" or not ha.ready():
        return
    failing = False
    while True:
        try:
            await asyncio.to_thread(ask, ha)
            failing = False
        except Exception as e:
            if not failing:
                log.info("language: no answer from Home Assistant yet (%s: %s)", type(e).__name__, e)
            failing = True
        await asyncio.sleep(30 if failing else LOOK_SECONDS)


def t(key, **values):
    """The text for key in the language in use (English when it's missing), filled in from values."""
    got = STRINGS[_lang].get(key, STRINGS["en"][key])
    return got.format(**values) if values and isinstance(got, str) else got

