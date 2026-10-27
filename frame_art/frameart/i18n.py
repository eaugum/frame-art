"""What Frame Art says, in English or Norwegian (AUG-1501): on the wall, in Home Assistant and on the add-on's page.

The language is `language` in the options: en, nb, or auto (the default), which follows Home Assistant's language
(GET /api/config). Any other language gives English. keep() looks it up in the background, since Home Assistant may
still be starting when the add-on does.
"""
import asyncio
import json
import logging

log = logging.getLogger(__name__)

LANGUAGES = ("en", "nb")
LOOK_SECONDS = 600  # Home Assistant's language is looked at again this often (every 30 s until it answers)

STRINGS = {
    "en": {
        # Morgenbildet
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
        # What's showing
        "label_morning": "Morning picture",
        "label_tonight": "Tonight: {title}",
        "label_music": "Music: {title} – {artist}",
        "not_changed": "Not changed yet",
        # Home Assistant (MQTT)
        "mqtt_model": "Art Mode for The Frame",
        "mqtt_shuffle": "Shuffle",
        "mqtt_fixed": "Fixed picture",
        "mqtt_morning": "Morning picture",
        "mqtt_tonight": "Tonight's show",
        "mqtt_screensaver": "Screensaver",
        "mqtt_screensaver_stasera": "Stasera in the screensaver",
        "mqtt_music": "Follow the music",
        "mqtt_music_home_only": "Only when someone is home",
        "mqtt_next": "Next picture",
        "mqtt_morning_now": "Morning picture now",
        "mqtt_tonight_now": "Tonight's show now",
        "mqtt_artmode": "Art Mode now",
        "mqtt_mode": "Mode",
        "mqtt_category": "Category",
        "mqtt_interval": "Interval",
        "mqtt_showing": "Picture",
        "mqtt_wanted": "In charge",
        "mqtt_picture": "The picture on the wall",
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
        "label_morning": "Morgenbildet",
        "label_tonight": "I kveld: {title}",
        "label_music": "Musikk: {title} – {artist}",
        "not_changed": "Ikke byttet ennå",
        "mqtt_model": "Kunstmodus for The Frame",
        "mqtt_shuffle": "Shuffle",
        "mqtt_fixed": "Fast bilde",
        "mqtt_morning": "Morgenbildet",
        "mqtt_tonight": "Kveldens serie",
        "mqtt_screensaver": "Skjermsparer",
        "mqtt_screensaver_stasera": "Stasera i skjermspareren",
        "mqtt_music": "Følg musikken",
        "mqtt_music_home_only": "Bare når noen er hjemme",
        "mqtt_next": "Neste bilde",
        "mqtt_morning_now": "Morgenbildet nå",
        "mqtt_tonight_now": "Kveldens serie nå",
        "mqtt_artmode": "Kunstmodus nå",
        "mqtt_mode": "Modus",
        "mqtt_category": "Kategori",
        "mqtt_interval": "Intervall",
        "mqtt_showing": "Bildet",
        "mqtt_wanted": "Styrer nå",
        "mqtt_picture": "Bildet på veggen",
    },
}

# The add-on's page: put into it as JSON when it's served (api.py)
PAGE = {
    "en": {
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
        "music_home_only": "Only when someone is home",
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
    },
    "nb": {
        "locale": "nb-NO",
        "new_picture": "Nytt bilde",
        "show_morning": "Vis Morgenbildet",
        "show_tonight": "Vis kveldens serie",
        "pictures": "Bildene",
        "recently_shown": "Nylig vist",
        "random": "Tilfeldige",
        "show_others": "Vis andre",
        "close": "Lukk",
        "settings": "Innstillinger",
        "interval": "Bytt bilde hvert",
        "keep": "Bilder som blir liggende på TV-en",
        "keep_note": "Under «Mine bilder» i Kunstmodus; de eldre slettes",
        "morning": "Morgenbildet",
        "morning_note": "Dato, vær, uke og navnedag og nytt i Stasera; avtaler og strøm fra valgene i HA",
        "tv_on": "Skru på TV-en først",
        "tv_on_note": "Gjennom Home Assistant, når den er av",
        "tv_on_missing": "Sett tv_entity i add-on-ets konfigurasjon",
        "tonight": "Kveldens serie",
        "tonight_note": "Fra «I kveld» i Stasera",
        "screensaver": "Skjermsparer",
        "screensaver_note": "Frame TV går i Kunstmodus når den står urørt",
        "screensaver_stasera": "Skjermspareren med Stasera-bildene",
        "screensaver_stasera_note": "Med tittel; ellers vanlig rotasjon",
        "music": "Følg musikken",
        "music_note": "Albumcoveret når det spilles musikk",
        "music_home_only": "Bare når noen er hjemme",
        "link": "Koble til",
        "unlink": "Koble fra",
        "tv_off": "TV-en er av. Vil du slå den på?",
        "tv_off_note": "Det tar et halvt minutt før bildet kommer.",
        "turn_on": "Slå på",
        "cancel": "Avbryt",
        "today_at": "i dag kl. {time}",
        "tomorrow_at": "i morgen kl. {time}",
        "reading": "leses …",
        "n_pictures": "{n} bilder",
        "no_pictures": "ingen bilder",
        "not_changed": "Ikke byttet ennå",
        "changed_at": "byttet {time}",
        "fixed": "Fast bilde",
        "fixed_until": "står til {when} ",
        "resume": "Fortsett rotasjonen nå",
        "coming": "kommer straks",
        "saver": "Skjermspareren",
        "saver_words": "Stasera-bildene, et nytt hvert {n}. minutt",
        "rotation": "Rotasjon",
        "rotation_words": "nytt bilde hvert {n}. minutt fra {sources}",
        "source_one": "{n} kilde",
        "source_other": "{n} kilder",
        "next_at": " · neste {time}",
        "standing": "står stille: ingen kilder er krysset av",
        "choose": "Velg bilde",
        "sum": "{on} av {total} kilder · {pictures} bilder",
        "none_ticked": "Ingen kilder er krysset av, så bildet byttes ikke.",
        "reading_sources": "Leser kildene som ikke er lest før …",
        "stasera_off": "Av: stasera_url mangler i valgene til add-on-et.",
        "stasera_linked": "Koblet. Kveldens serie kommer fra «I kveld».",
        "stasera_approve": "Godkjenn koden {code} i {stasera}.",
        "stasera_unlinked": "Ikke koblet.",
        "stasera_no_answer": "Fikk ikke svar fra Stasera.",
        "turning_on": "Slår på TV-en … {doing}",
        "done": "Ferdig.",
        "failed": "Gikk ikke: {error}",
        "unknown_error": "ukjent feil",
        "no_answer": "Fikk ikke svar.",
        "saved": "Lagret",
        "not_saved": "Ikke lagret: {error}",
        "couldnt_save": "Fikk ikke lagret.",
        "showing_until": "Viser bildet og lar det stå til Morgenbildet …",
        "fetching": "Henter …",
        "gallery_off": "Ingen av kildene i {name} er krysset av.",
        "gallery_reading": "Leser {names} (første gang tar det litt). Trykk «Vis andre» om litt. ",
        "gallery_empty": "Ingen bilder her. ",
        "gallery_hint": "Et bilde du trykker på, står til neste Morgenbildet.",
        "fetching_new": "Henter et nytt bilde og sender det til TV-en …",
        "making_morning": "Lager Morgenbildet …",
        "making_tonight": "Lager plakaten for kveldens serie …",
    },
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


def page():
    """The page's strings, in the language in use."""
    return dict(PAGE["en"], **PAGE[_lang])
