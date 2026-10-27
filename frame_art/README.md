# Frame Art

Our own rotation in Art Mode on The Frame (TQ50LS03B, 2022, Tizen 6.5, 10.1.2.36), instead of the Samsung Art Store
(AUG-1438). It changes the picture by itself at a fixed interval, to a random picture from a random source that's on,
and tidies its own old pictures in "My Photos". It never touches the other pictures there. It uses
[NickWaterton/samsung-tv-ws-api](https://github.com/NickWaterton/samsung-tv-ws-api).

It runs as a local add-on in Home Assistant OS on the Pi (10.1.2.12), but needs nothing from HA. It could just as well
run with Python on anything that's on at home.

**It must run from the 10.1.2 network** (the same network as the TV). From 10.1.1.x the TV answers
`ms.channel.timeOut` at once, without asking for access. The first connection from a new machine gives an "Allow"
prompt on the TV, so the TV has to be on then; the token is saved in `token.txt` (gitignored).

## Language

What Frame Art says is in English or Norwegian: the morning picture and the posters on the wall, the device in Home
Assistant and the add-on's page. `language` in the options is `auto` (Home Assistant's language; English when it's
neither English nor Norwegian), `en` or `nb`. With `auto`, a change of language in HA comes along within ten minutes.
The name days are only on the Norwegian morning picture. The electricity price follows the sensor's currency, not the
language: øre and kroner for NOK, otherwise the number with its unit. The strings are in `frameart/i18n.py`.

## The sources

The sources are a list in the options (`sources`), so a new source is a few lines in Home Assistant: Settings →
Add-ons → Frame Art → Configuration → ⋮ → Edit in YAML. After a restart the add-on's page shows how many pictures each
source found; 0 usually means a wrong name (the log says which).

```yaml
- name: Abstract                  # shown in front of the title; no colon
  category: Abstract              # several sources can share a category; without it, the category is the name
  type: commons
  query: Paintings by Hilma af Klint|Paintings by Piet Mondrian   # several with |
```

Every source in the list is included; which ones the rotation draws from is ticked on the add-on's page. `years`,
`shape`, `weight` and `enabled` from before 0.15 are ignored. The default sources have English names from 0.20; sources
already saved in the options keep their names.

| Type | What | `query` |
|---|---|---|
| `folder` | The pictures in a folder (and subfolders) | The folder (`/media/frame-art`) |
| `met` | The Met, public domain; paintings unless said otherwise | Search words, or the search's fields: `medium=Prints&q=Hiroshige` |
| `rijksmuseum` | Rijksmuseum (everything with a picture is public domain); paintings unless said otherwise | Words in the description (`zee`), or fields: `creator=Vermeer` |
| `nasjonalmuseet` | The Nasjonalmuseet's paintings on Wikimedia Commons | Artists (`Hans Gude`) |
| `cleveland` | Cleveland Museum of Art, CC0; paintings unless said otherwise | Search words, or fields: `type=Print&q=Hokusai` |
| `smk` | Statens Museum for Kunst, Copenhagen, public domain; paintings unless said otherwise | Search words (`landskab`), `*` for everything, or fields: `keys=*&object_names=tegning` |
| `commons` | Wikimedia Commons categories, with subcategories two levels down (everything there is free) | Category names without `Category:`, e.g. `Featured pictures of Norway` |
| `nasa` | NASA's image library | Search words (`nebula`) |
| `wellcome` | Wellcome Collection, public domain and CC0: old illustrations | Search words (`botanical`) |
| `stasera` | The backdrops (without text where there are some) of what we watch in Stasera. Needs `stasera_url` and the add-on linked to Stasera | The lists: `watching`, `wantToStart`, `movies`, `recommendations` |

Only pictures close to 16:9 are used (from 3:2 to a little wider than 16:9, 1.45–2.0), cropped to fill the screen;
from the museums, Commons, NASA, Wellcome and Stasera they must also be at least 1920 px wide. The rest are left out
when the source is read, and a picture in the folder that doesn't fit is skipped and doesn't come again. `shape` from
before 0.14 is ignored. Sources with mostly portrait pictures (posters, woodblock prints) therefore get few pictures.
The Art Institute of Chicago isn't included: the pictures are behind a Cloudflare check a script can't get past. The
Nasjonalmuseet's own API is down until v2 comes, and DigitaltMuseum gives at most 1200 px, hence Commons. Europeana,
Smithsonian and Harvard each need a key and aren't included yet. The film pictures from Stasera (they're at TMDB)
aren't free, but for use at home.

The options from 0.3 (`museums`, `met_queries` etc.) still work when `sources` is missing, e.g. in an old
`options.json`.

Each source is drawn equally often, however many pictures it has. No picture comes again before 200 others have been
shown (or the whole source, if it's smaller).

The change: if the TV is in Art Mode, the picture is shown at once; otherwise it's selected and ready for the next time
Art Mode is turned on, and what's on the screen stays. If the art app doesn't answer (the TV off, AirPlay, right after
Art Mode is turned on), it tries again every 5 minutes with the same picture, without interrupting anything. How many
of our own pictures stay on the TV (3) is on the add-on's page.

Access: the Art Mode channel never asks "Allow"; it just stays silent without a token. Without a token the service
therefore first connects to the remote control channel (without sending keys). Then the prompt comes on the TV, and the
token works for both.

## The sources and the categories

The rotation draws from the sources ticked on the add-on's page. Each source is under its category (`category`); the
defaults have seven: My pictures, Paintings, Abstract, Japan, Posters, Nature and space, and Film. The tick by a
category turns all its sources on or off.

A source is read (the list of its pictures fetched) the first time it's drawn, and all that have never been read are
read in the background when the add-on starts.

**A fixed picture:** "Choose picture" by a category shows what's been shown lately and 24 at random, from its sources
that are ticked. A picture you press is shown at once and stays until the next morning picture; then the rotation goes
on. "New picture", a new tick or "Resume the rotation now" ends it sooner.

The ticks are saved in `/data/settings.json` (`sources_off`), like the schedule.

**What wins**, top first. When the top one is done, the next takes over.

1. Follow the music, when it's on and music is playing
2. What you choose yourself: a fixed picture, or "New picture"
3. The morning picture and tonight's show. A fixed picture is ended by the morning picture, not by tonight's show.
4. The screensaver
5. The usual rotation, in its mode

## The morning picture and tonight's show (AUG-1447)

The add-on makes two pictures itself, once a day each, as soon as their time comes. After that the rotation goes on as
before.

- **The morning picture** (`morning_time`, 07:00): the weekday, the date, the day's highest and lowest temperature,
  the weather in words ("rain from 15:00") and sunrise and sunset, in calm type on a surface coloured by the weather.
  The weather comes from `weather_entity` in the options (`weather.forecast_home`: met.no, as Yr) and the sun from
  `sun.sun` in HA. Under the weather are the temperatures at 8, 12, 16 and 20, and when needed the wind (from fresh
  breeze, 8 m/s: "Strong breeze from the southwest, gusts 18 m/s") and "Risk of icy roads" (precipitation between −3
  and 1.5 degrees before 12). If it's empty or doesn't answer, the picture comes without weather. Under the date are
  the week and, in Norwegian, the name day (Almanakkforlaget's list, revised December 2025, in `navnedager.json`;
  `scripts/navnedager.py` makes it again). On the right, when they have something:
  - **Today:** the events from the calendars in `calendars` in the options (`calendar.*` in HA).
  - **New in Stasera:** new episodes, season and series premieres and film premieres today (`/tv/upcoming`).
  - **Electricity:** the price hour by hour as bars, and the cheapest and dearest two hours for the rest of the day
    (`price_entity` in the options): a Nord Pool sensor with `raw_today` or `today`, or Tibber's price sensor
    (`sensor.<home>_electricity_price`), then with the prices from `tibber.get_prices`.
- **Tonight's show** (`tonight_time`, 18:00): a poster of the first in Stasera's "Tonight", with the backdrop without
  text, the logo (or the title) and the season and episode. Needs `stasera_url` and the add-on linked to Stasera. If
  there's nothing tonight, there's no poster.

If the TV is off when the time comes, the picture waits until it's on again, but the morning picture only until
tonight's time. If it couldn't make the picture (the network), it tries again in 15 minutes.

**Turn the TV on first:** with `tv_entity` in the options (a media player in HA, e.g.
`media_player.stue_the_frame_stue`) and the switch "Turn the TV on first" on the add-on's page on (it is by default):
if the TV is off when the morning picture is due, HA turns it on (`media_player.turn_on`, once a day), and the morning
picture comes in Art Mode.

## The screensaver and the way back (AUG-1494)

When Frame TV's screensaver starts (`POST /saver`), the add-on turns on Art Mode. With "Screensaver" off
(`screensaver`, `switch.frame_art_screensaver`) Frame TV starts no screensaver; it reads the option from `/status`.
With "Stasera in the screensaver" on (`screensaver_stasera`) what we watch and want to start in Stasera comes next, as
posters with "WATCHING" or "WANT TO START", the title (or the logo) and the next episode, in turn with the interval.
Without it, or without Stasera: the usual rotation. A fixed picture, the morning picture and tonight's show go first. A
picture still on the TV is selected there instead of being sent again.

The screensaver lasts until Art Mode is turned off. A key on the remote in Art Mode (Back, power) gives the TV's own
Art Mode menu, which only has the way Home → the app. So the add-on listens on the art channel: if Art Mode goes off
while the TV is on, it opens Frame TV (`FrameTVapp.FrameTV`) over the TV's REST API on port 8001. That happens every
time, not just after the screensaver.

**The schedule on the add-on's page:** how often the picture changes, and on/off and the time for the two pictures. It
works at once, without a restart, and is saved in `/data/settings.json`, before the add-on's options.

**Stasera:** "Link" on the add-on's page gives a code and a link; approve it in Stasera, as when the TV is linked. The
token is in `/data/stasera_token.txt`. "Unlink" forgets it.

## Follow the music (AUG-1495)

With "Follow the music" on (`music`, off by default) the album cover comes on the wall when Spotify plays: big, on a
surface in the cover's colours, with the song, the artist and the album. The player is read from Home Assistant
(`homeassistant_api`), so no Spotify key is needed here, only the Spotify or SpotifyPlus integration in HA: the first
`media_player.spotify*` that plays. The picture changes for each song, 10–20 seconds after it starts.

It goes in front of everything else, a fixed picture too, but doesn't turn on Art Mode itself. Three minutes after the
music stops (pause, stop) the picture that was there before comes back. If the morning picture or tonight's show has
had its time meanwhile, that comes instead. "Only when someone is home" (`music_home_only`) follows the music only when
`zone.home` has someone in it; without it, all playback on the account is followed. Outside HA it needs `ha_url` and
`ha_token` in the options.

## Controlling it: Home Assistant and Frame TV

The add-on answers on port 8099 on the home network. Every call needs the key, as `Authorization: Bearer <key>` or
`?key=<key>`: `api_key` in the options. If it's empty, the add-on makes one and writes it there itself. The page in HA
doesn't need it. The answers wait for the TV.

| Call | What |
|---|---|
| `GET /status` | What's showing, when it changed and when it changes next, the mode (`mode`: `shuffle` or `fixed`), the categories, the number of pictures per source (`pools`, `null` before it's read) and the options |
| `GET /tv` | Whether the TV is off (`{"off": true}`), from `tv_entity`; `null` without it |
| `POST /next` | A new picture now; `?art_mode=1` puts the TV in Art Mode too, `?what=morning` shows the morning picture and `?what=tonight` tonight's show. `?wake=1` (on `/show` too) turns the TV on first when it's off. Ends a fixed picture |
| `POST /artmode` | Art Mode on, with the picture it has |
| `GET /category?name=Japan` | Recently shown and 24 at random from the category's sources that are ticked, to choose a picture |
| `GET /thumb?key=…` | A small picture of a key from `/category` |
| `POST /show?key=…` | That picture now, in Art Mode, as a fixed picture until the next morning picture |
| `POST /settings` | Changes the options, with JSON: `sources_off` (the sources not ticked), `mode` (`shuffle` ends a fixed picture; `category` with `category` ticks only that category), `interval_minutes`, `keep`, `morning`, `morning_time`, `tonight`, `tonight_time`, `screensaver`, `screensaver_stasera`, `music`, `music_home_only`. `/schedule` is the same |
| `POST /saver` | Frame TV's screensaver started: Art Mode on, and the Stasera pictures until Art Mode is turned off (see above). `?minutes=5` changes the picture that often meanwhile (the option is in Frame TV) |
| `POST /stasera/link`, `/stasera/unlink` | Links to Stasera (the code is in `/status` under `pairing`) and unlinks |

Art Mode is turned on with `set_artmode`. If that doesn't take, one short press of power is sent over the remote
control channel, but only when the TV has just said it's on and not in Art Mode. The timer alone never turns on Art
Mode.

- **Home Assistant:** the device over MQTT (see below); scripts and automations press its buttons, e.g.
  `button.press` on `button.frame_art_next`.
- **Frame TV:** `art_url=http://10.1.2.12:8099` and `art_key=<the key>` in `config.properties`. The tile on Home: OK
  turns on Art Mode, hold OK for a new picture. When the screensaver starts, it says so with `POST /saver`.

## As a device in Home Assistant (MQTT)

With the Mosquitto broker add-on and the MQTT integration in HA, Frame Art announces itself as the device **Frame
Art**; the connection comes from the Supervisor, with nothing in the options. Without Mosquitto the add-on runs as
before. The names are in the add-on's language; the entity ids are the same in any language.

| Entity | What |
|---|---|
| `button.frame_art_next`, `_morning_now`, `_tonight_now`, `_artmode` | Next picture, the morning picture now, tonight's show now, Art Mode on |
| `select.frame_art_mode` | Shuffle or Fixed picture (what's showing now stays until the next morning picture) |
| `select.frame_art_category` | The categories from the sources; choosing one ticks only its sources |
| `number.frame_art_interval` | Minutes between the changes |
| `switch.frame_art_morning`, `_tonight` | The morning picture and tonight's show |
| `switch.frame_art_screensaver`, `_screensaver_stasera`, `_music`, `_music_home_only` | The screensaver and Follow the music |
| `sensor.frame_art_showing` | The picture's title; source, category, when it changed and the next change as attributes |
| `sensor.frame_art_wanted` | What decides now: `music`, `rotation`, `fixed`, `morning`, `tonight` or `saver` |
| `image.frame_art_picture` | The picture on the wall, 1280 px wide |

The state is sent when it changes (from HA, the add-on's page or the timer). A new category in the sources comes into
the select after a restart of the add-on. A card for the dashboard:

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

## In Home Assistant

1. Settings → Add-ons → Add-on Store → ⋮ → Repositories → add `https://github.com/eaugum/frame-art`.
2. **Frame Art** is under "Frame Art". Install it (the Pi builds it itself, which takes a few minutes), look over the
   options and start it. Answer "Allow" on the TV the first time. The log shows every change.
3. A new version here gives "Update available" in HA (⋮ → Check for updates to see it at once).

**Your own pictures:** Media → Local media → make the folder `frame-art` and upload the pictures there (or copy them to
`/media/frame-art` over Samba). The source `type: folder` with `query: /media/frame-art` shows them. JPEG and PNG are
fine; HEIC from an iPhone isn't read.

## On a Mac or another machine

```bash
cd frame_art
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m frameart --config options.json --preview out   # makes 5 pictures in out/, doesn't touch the TV
.venv/bin/python -m frameart --config options.json --preview out --what morning   # only the morning picture (or tonight)
.venv/bin/python -m frameart --config options.json --once          # changes the picture once
.venv/bin/python -m frameart --config options.json                 # runs by itself
```

`options.json` has the same options as `config.yaml`. The token, `state.json` and the next picture end up next to it
(`--data` for another folder).

## The test scripts (AUG-1430)

| Script | What |
|---|---|
| `../scripts/probe.py` | Art Mode on/off, the current picture, the slideshow, the pictures on the TV |
| `../scripts/upload_test.py` | Makes a 4K test picture and uploads it (not shown) |
| `../scripts/remote_probe.py` | Connects to the remote control channel (gives the permission prompt) |
| `../scripts/raw.py` | A raw WebSocket test on port 8001/8002, with the response time |

Result on 24.10.2026: API 4.3.4.0 is supported, uploading works (ends up in `MY-C0002`).
