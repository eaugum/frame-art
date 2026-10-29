# Frame Art

Frame Art runs Art Mode on a Samsung The Frame from Home Assistant. It changes the picture at an interval you choose,
to a random picture from the sources you've ticked, and it tidies its own old pictures in "My Photos" on the TV without
touching anything else there. It talks to the TV with
[samsung-tv-ws-api](https://github.com/NickWaterton/samsung-tv-ws-api).

## Getting started

1. Settings → Add-ons → Add-on Store → ⋮ → Repositories → add `https://github.com/eaugum/frame-art`.
2. Install **Frame Art**. Home Assistant builds it itself, which takes a few minutes.
3. In the options, set `tv_host` to the TV's IP address. Giving the TV a fixed address in your router is a good idea.
4. Turn the TV on and start the add-on. The first time, the TV asks whether to allow the connection: choose **Allow**.
   The log shows every change of picture.
5. Open **Frame Art** in the sidebar and tick the sources you want.

New versions show up as "Update available" in Home Assistant (⋮ → Check for updates to see one at once).

**The TV and Home Assistant must be on the same local network.** If the TV is on a separate network or VLAN, it may
refuse the connection without ever showing the Allow prompt.

## Options

What's set up once is in the add-on's options. What you change from day to day (which sources are ticked, the
interval, the times and the switches) is on the add-on's page and is saved in `/data/settings.json`.

| Option | What |
|---|---|
| `tv_host` | The TV's IP address |
| `language` | The language of the morning picture and the posters: `auto` (default), `en` or `nb`. See [Language](#language) |
| `api_key` | The key for the API. Left empty, the add-on makes one and writes it in |
| `weather_entity` | The weather for the morning picture, e.g. `weather.forecast_home` (Met.no). Empty gives no weather |
| `tv_entity` | The TV as a `media_player` in Home Assistant, turned on before the morning picture and tonight's show when it's off. Empty: never |
| `home_entity` | Who's home, for "Only when someone is home": `zone.home` (default; someone in it), or a `person`, `device_tracker`, `group`, `binary_sensor` or `input_boolean` that is `home` or `on`. Empty: always home |
| `calendars` | `calendar.*` entities whose events today are shown on the morning picture |
| `price_entity` | A Nord Pool or Tibber price sensor for the morning picture |
| `stasera_url` | [Stasera](https://www.stasera.app), for tonight's show, the screensaver posters and the film sources. Optional |
| `back_app` | The id of a TV app to open when Art Mode is turned off while the TV is on, e.g. a home screen app. Empty (default): none |
| `sources` | Where the pictures come from. See [Sources](#sources) |

## Language

The add-on's page, its device in Home Assistant and the options are in English. The morning picture and the posters on
the wall are in English or Norwegian. With `language: auto` they follow Home Assistant's **system** language (Settings →
System → General), not the language in your user profile; any language other than Norwegian gives English. A change
of language in Home Assistant comes along within ten minutes.

The Norwegian morning picture also shows the day's name day. The electricity price follows the sensor's currency, not
the language: øre and kroner for NOK, otherwise the number with its unit.

## Sources

The sources are a list in the options. To add one: Settings → Add-ons → Frame Art → Configuration → ⋮ → Edit in YAML.
After a restart the add-on's page shows how many pictures each source found; 0 usually means a wrong name, and the log
says which.

```yaml
- name: Abstract                  # shown in front of the title; no colon
  category: Abstract              # several sources can share a category; without it, the category is the name
  type: commons
  query: Paintings by Hilma af Klint|Paintings by Piet Mondrian   # several with |
```

| Type | What | `query` |
|---|---|---|
| `folder` | The pictures in a folder and its subfolders | The folder, e.g. `/media/frame-art` |
| `met` | The Met, public domain; paintings unless said otherwise | Search words, or the search's fields: `medium=Prints&q=Hiroshige` |
| `rijksmuseum` | The Rijksmuseum, public domain; paintings unless said otherwise | Words in the description (`zee`), or fields: `creator=Vermeer` |
| `nasjonalmuseet` | Paintings from the Nasjonalmuseet in Oslo, through Wikimedia Commons | Artists (`Hans Gude`) |
| `cleveland` | The Cleveland Museum of Art, CC0; paintings unless said otherwise | Search words, or fields: `type=Print&q=Hokusai` |
| `smk` | Statens Museum for Kunst, Copenhagen, public domain; paintings unless said otherwise | Search words (`landskab`), `*` for everything, or fields: `keys=*&object_names=tegning` |
| `commons` | Wikimedia Commons categories, with subcategories two levels down | Category names without `Category:`, e.g. `Featured pictures of Norway` |
| `nasa` | NASA's image library | Search words (`nebula`) |
| `wellcome` | Wellcome Collection, public domain and CC0: old illustrations | Search words (`botanical`) |
| `stasera` | Backdrops of what you watch in Stasera, without text where there is a version without. Needs `stasera_url` and the add-on linked to Stasera | The lists: `watching`, `wantToStart`, `movies`, `recommendations` |
| `tmdb` | Backdrops without text from TMDB, through Stasera: up to 5 per film or show, 4K where there is, short films left out. Needs `stasera_url` and the add-on linked to Stasera | TMDB ids: `company=3` (a studio's films), `collection=10` (a film series), `tv=82856` (a show), `movie=330459`, `keyword=…`; `&genre=16` narrows a studio down to animation, e.g. `company=3166&genre=16` |

**What fits:** only pictures close to 16:9 are used (from 3:2 to a little wider than 16:9), cropped to fill the
screen. Pictures from the online sources must also be at least 1920 pixels wide. The rest are left out when the source
is read, so sources with mostly portrait pictures, like posters and woodblock prints, give fewer pictures.

**Your own pictures:** Media → Local media → make the folder `frame-art` and upload the pictures there, or copy them to
`/media/frame-art` over Samba. The default source "My pictures" shows them. JPEG and PNG work; HEIC from an iPhone
doesn't.

**How they're drawn:** every source is drawn equally often, however many pictures it has, and no picture comes again
before 200 others have been shown (or the whole source, if it's smaller). A source is read the first time it's drawn;
sources that have never been read are read in the background when the add-on starts.

**Categories:** the defaults have thirteen: My pictures, Paintings, Abstract, Japan, Posters, Nature and space, Film,
Pixar, Disney, Star Wars, Studio Ghibli, DreamWorks and Marvel. On the add-on's page each source is under its
category, and the tick by a category turns all of its sources on or off.

**Film and animation:** Pixar, Disney (Walt Disney Animation Studios and the classics), Star Wars (the saga, Rogue One,
Solo and the shows), Studio Ghibli, DreamWorks Animation and Marvel Studios are `tmdb` sources: backdrops without text
from TMDB, fetched through Stasera, so they need the add-on linked to Stasera. The first time a studio is asked for,
Stasera fetches it in the background, and the pictures come a minute or two later. Options saved before 0.22.0 don't have them; add these under `sources`:

```yaml
- {name: Pixar, type: tmdb, query: company=3}
- {name: Disney, type: tmdb, query: company=6125|company=3166&genre=16}
- {name: Star Wars, type: tmdb,
   query: collection=10|movie=330459|movie=348350|tv=4194|tv=82856|tv=83867|tv=115036|tv=92830|tv=114461}
- {name: Studio Ghibli, type: tmdb, query: company=10342}
- {name: DreamWorks, type: tmdb, query: company=521}
- {name: Marvel, type: tmdb, query: company=420}
```

Official wallpapers and concept art
aren't on TMDB; download them yourself and put them in a folder source in the same category:

```yaml
- {category: Pixar, name: Pixar wallpapers, type: folder, query: /media/frame-art/pixar}
```

The film pictures from Stasera come from TMDB and aren't free, but are for use at home. Everything else is public
domain or free to use.

## The add-on's page

Open **Frame Art** in the sidebar. A line under the title says what's in charge now. From the page you can:

- show a new picture, the morning picture or tonight's show at once,
- turn Follow the music on or off with its button by the others (it's lit when it's on),
- turn the TV on: "Turn the TV on" is there while the TV is off (with `tv_entity` set). It turns the TV on through Home Assistant
  and opens `back_app` (Frame TV: `FrameTVapp.FrameTV`); without `back_app`, the TV stays where it comes up,
- tick sources and categories,
- **choose a picture**: "Choose picture" by a category shows what's been shown lately and 24 at random. The picture
  you press is shown at once and stays until the next morning picture. "New picture" or "Resume the rotation now" ends it
  sooner,
- set how often the picture changes, how many of Frame Art's pictures stay on the TV, and the times for the morning
  picture and tonight's show,
- turn the screensaver on or off,
- leave out the picture on the wall for good: "Don't show again" in the picture's corner, then yes to the question
  (a backdrop with a logo after all, or a picture you don't like). Another one comes at once,
- link the add-on to Stasera.

The **Debug** tab lists what the add-on did and what it saw the TV do, newest first: when, what and why (the timer,
the morning picture at 07:00, Home Assistant, Frame TV or the page). A button per source shows or hides its events, and
"A day earlier" goes back. The last 7 days are kept in `/data/events.jsonl`.

**What wins**, top first. When the top one is done, the next takes over.

1. Follow the music, when it's on and music is playing
2. What you choose yourself: a fixed picture, or "New picture"
3. The morning picture and tonight's show. A fixed picture is ended by the morning picture, not by tonight's show
4. The screensaver
5. The usual rotation

**When the picture changes:** if the TV is in Art Mode, the new picture is shown at once. Otherwise it's made ready for
the next time Art Mode is turned on, and whatever is on the screen stays. If the TV doesn't answer (it's off, or busy
with AirPlay), Frame Art tries again every 5 minutes with the same picture, without interrupting anything. The timer
alone never turns on Art Mode.

## The morning picture

At `morning_time` (07:00 by default) Frame Art makes a picture of the day, in calm type on a surface coloured by the
weather:

- the weekday and the date, the week number and, in Norwegian, the name day,
- the day's highest and lowest temperature, the weather in words ("Rain from 15:00"), sunrise and sunset, and the
  temperatures at 8, 12, 16 and 20, from `weather_entity` and `sun.sun`,
- the wind when it's at least a fresh breeze, and "Risk of icy roads" when there's precipitation around zero in the
  morning,
- on the right, when there's something to show: today's events from `calendars`, what's new in Stasera today, and the
  electricity price hour by hour as bars, with the cheapest and dearest two hours for the rest of the day.

The price works with a Nord Pool sensor (`raw_today` or `today`) or Tibber's price sensor
(`sensor.<home>_electricity_price`), whose prices come from `tibber.get_prices`. Without a weather entity, or if it
doesn't answer, the picture comes without weather.

**Turn the TV on first:** with `tv_entity` set and the switch "Turn the TV on first" on (it is by default), Home
Assistant turns the TV on when it's off at the morning picture's time, once a day, and the picture comes up in Art
Mode. With "Only when someone is home" on (it is by default), only when `home_entity` says someone is. Otherwise the
morning picture waits until the TV is on, but only until tonight's show.

A morning picture you ask for yourself before `morning_time` ("Morning picture now") doesn't count as the day's: the
morning picture still comes at its time.

## Tonight's show (Stasera)

With [Stasera](https://www.stasera.app) linked, Frame Art makes a poster at `tonight_time` (18:00 by default) of the
first show in Stasera's "Tonight": the backdrop, the logo or the title, and the season and episode. If there's nothing
tonight, there's no poster.

Tonight's show has its own "Turn the TV on first", which works like the morning picture's.

To link: press "Link" on the add-on's page, and approve the code in Stasera. "Unlink" forgets it.

## The screensaver

`POST /saver` turns on Art Mode, for a screensaver or an automation. With "Stasera in the screensaver" on, posters of
what you're watching and want to start in Stasera come next, in turn; otherwise the usual rotation. With the switch
"Screensaver" off, `/status` says so, for apps that start the screensaver themselves.

## Follow the music

With "Follow the music" on (it's off by default), the album cover comes on the wall when Spotify plays: big, on a
surface in the cover's colours, with the song, the artist and the album. The player is read from Home Assistant (the
Spotify or SpotifyPlus integration, the first `media_player.spotify*` that plays), so no Spotify key is needed. The
picture changes for each song.

It goes in front of everything else, but doesn't turn on Art Mode by itself. Three minutes after the music stops, the
picture from before comes back. "Only when someone is home" follows the music only when `home_entity` (`zone.home` by default) says someone is home;
the same switch is for turning the TV on before the morning picture and tonight's show.

## In Home Assistant (MQTT)

With the Mosquitto broker add-on and the MQTT integration, Frame Art shows up as the device **Frame Art**, with nothing
to set up. Without Mosquitto it runs as before.

| Entity | What |
|---|---|
| `button.frame_art_next`, `_morning_now`, `_tonight_now`, `_artmode` | Next picture, the morning picture now, tonight's show now, Art Mode on |
| `select.frame_art_mode` | Shuffle, or Fixed picture (what's showing stays until the next morning picture) |
| `select.frame_art_category` | The categories; choosing one ticks only its sources |
| `number.frame_art_interval` | Minutes between the changes |
| `switch.frame_art_morning`, `_tonight` | The morning picture and tonight's show |
| `switch.frame_art_screensaver`, `_screensaver_stasera`, `_music` | The screensaver and Follow the music |
| `switch.frame_art_music_home_only` | Only when someone is home: Follow the music, and turning the TV on |
| `sensor.frame_art_showing` | The picture's title, with the source, the category, when it changed and the next change as attributes |
| `sensor.frame_art_wanted` | What's in charge: `music`, `rotation`, `fixed`, `morning`, `tonight` or `saver` |
| `image.frame_art_picture` | The picture on the wall, 1280 pixels wide |

A new category comes into the select after a restart of the add-on. A dashboard card:

```yaml
type: vertical-stack
cards:
  - type: picture-entity
    entity: image.frame_art_picture
    name: Art Mode
  - type: entities
    entities:
      - sensor.frame_art_showing
      - select.frame_art_mode
      - select.frame_art_category
      - button.frame_art_next
      - button.frame_art_artmode
```

## The API

The add-on answers on port 8099 on the local network, for scripts and apps on the TV. Every call needs the key, as
`Authorization: Bearer <key>` or `?key=<key>`; it's `api_key` in the options. The page in the sidebar doesn't need it.
The answers wait for the TV.

| Call | What |
|---|---|
| `GET /status` | What's showing, when it changed and changes next, the mode, the categories, the number of pictures per source and the settings |
| `GET /tv` | Whether the TV is off (`{"off": true}`), asked of the TV; `null` without `tv_entity` |
| `POST /tv/on` | The TV on through Home Assistant (`tv_entity`), then `back_app` opened. Doesn't wait for the TV's turn, so it answers while the add-on waits for a sleeping TV |
| `POST /next` | A new picture now. `?art_mode=1` turns on Art Mode too, `?what=morning` or `?what=tonight` shows that picture, and `?wake=1` turns the TV on first when it's off. Ends a fixed picture |
| `POST /artmode` | Art Mode on, with the picture it has |
| `POST /never` | The picture on the wall is never shown again, and another comes; only for a picture from a source (`showing_key` in `/status`) |
| `GET /category?name=Japan` | Recently shown and 24 at random from the category's ticked sources |
| `GET /thumb?key=…` | A small copy of a picture from `/category` |
| `POST /show?key=…` | That picture now, in Art Mode, fixed until the next morning picture |
| `POST /settings` | Changes the settings, with JSON: `sources_off`, `mode`, `interval_minutes`, `keep`, `morning`, `morning_time`, `morning_tv_on`, `tonight`, `tonight_time`, `tonight_tv_on`, `screensaver`, `screensaver_stasera`, `music`, `music_home_only` |
| `POST /saver` | The screensaver: Art Mode on (see above). `?minutes=5` changes the picture that often meanwhile |
| `POST /stasera/link`, `/stasera/unlink` | Links to Stasera (the code is in `/status` under `pairing`) and unlinks |
| `GET /events?since=<id>` | What happened, oldest first: `{"events": [{id, at, source, kind, detail, why}], "more": false}`, the newest 2000 after that id (an id is the time in ms). `?until=<id>` for those before one |

Art Mode is turned on with the Art Mode API. If that doesn't take, Frame Art sends one short press of the power key,
but only when the TV has just said it's on and not in Art Mode.

## Troubleshooting

- **No Allow prompt on the TV:** the TV has to be on, and on the same network as Home Assistant. The Art Mode channel
  never asks by itself, so Frame Art first connects to the remote control channel (without sending keys) to get the
  prompt. The token it gets is saved in `/data/token.txt`; delete it to ask again.
- **A source has 0 pictures:** the name or the query is probably wrong; the log says which.
- **The morning picture has no weather:** check `weather_entity`.

## Running it without Home Assistant

Frame Art needs nothing from Home Assistant except for the weather, the calendars, the price, Follow the music and the
MQTT device. It runs with Python on any machine on the same network as the TV:

```bash
cd frame_art
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m frameart --config options.json --preview out                  # 5 pictures in out/, the TV untouched
.venv/bin/python -m frameart --config options.json --preview out --what morning   # only the morning picture (or tonight)
.venv/bin/python -m frameart --config options.json --once                         # changes the picture once
.venv/bin/python -m frameart --config options.json                                # runs by itself
```

`options.json` has the same options as `config.yaml`; outside Home Assistant, `ha_url` and `ha_token` give it access
to Home Assistant. The token, the state and the next picture end up next to it (`--data` for another folder).

`../scripts/` has test scripts for troubleshooting the TV: `probe.py` (Art Mode, the current picture, the pictures on
the TV), `upload_test.py` (uploads a 4K test picture), `remote_probe.py` (the remote control channel and its prompt)
and `raw.py` (a raw WebSocket test).
