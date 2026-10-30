# Changes

## 0.29.0

- The morning picture and tonight's show stay until they've been seen: when the TV goes off or out of Art Mode within
  10 minutes of them (the TV's own sleep in a dark room, say), the rotation counts from when Art Mode is on again,
  instead of changing the picture as soon as it comes back. The Debug tab says so ("the morning picture stays: the TV
  went to standby right after it").

## 0.28.0

- The rotation waits while the TV is off or out of Art Mode, instead of sending pictures nobody sees; when Art Mode
  comes on again and the interval has passed, a new one comes at once. The Debug tab says when it started waiting, and
  why. While the TV's state isn't known, the rotation goes on as before.
- When the TV closes the art channel, Art Mode counts as not known, not as what it was last heard to be.

## 0.27.0

- The add-on's page says when the picture isn't on the wall: when the TV is on without Art Mode, the picture is
  dimmed, marked "The TV isn't in Art Mode", with "Ready for the next time Art Mode comes on." and a "Turn Art Mode on"
  button; when the TV is off, the mark says so. While the TV's state isn't known, the page is as before.

## 0.26.0

- The Debug tab shows a day at a time, with a timeline at the top: when the TV was on, in Art Mode, showing Frame TV,
  the screensaver and the music, and when the morning picture and tonight's show came. ‹ and › go between the days.
- "Export as JSON" downloads the whole log (`GET /events/export`).
- Three new entities in Home Assistant: `binary_sensor.frame_art_tv_on`, `binary_sensor.frame_art_art_mode` and
  `sensor.frame_art_activity` (off, app, art, morning, tonight, saver, music), so the history shows what the TV did.
- The events are in the order they happened, also those Frame TV sent later.

## 0.25.0

- The Debug tab follows the TV: the add-on asks every 20 seconds whether it's on, and hears when Art Mode goes on or
  off. A change that comes soon after something Frame Art did says what that was; any other is marked "from outside"
  (the remote, the motion sensor, the TV's own sleep).
- Frame TV's own events are in the log too (`POST /event`): started, hidden and shown, what it opened, its screensaver
  and errors, also those it sent later while the add-on didn't answer.

## 0.24.0

- A Debug tab on the add-on's page: what the add-on did and what it saw the TV do, newest first, with when, what and
  why (the timer, the morning picture at 07:00, Home Assistant, Frame TV or the page). A button per source shows or
  hides its events. The last 7 days are kept in `/data/events.jsonl`, and `GET /events` gives them as JSON.

## 0.23.2

- "Don't show again" is in the top right corner of the picture on the add-on's page, not among the buttons, and asks
  first. It's hidden while the cover of Follow the music stands.

## 0.23.1

- "Turn the TV on" now shows when the TV is off. Whether it's off is asked of the TV itself: Home Assistant's
  `tv_entity` could say "on" for a TV that was asleep and didn't answer. The same goes for turning the TV on before the
  morning picture and tonight's show.
- While Follow the music shows the cover, "New picture" and the other picture buttons are greyed out, and so is
  choosing a picture; the line at the top says to turn Follow the music off first.

## 0.23.0

- "Turn the TV on" on the add-on's page, while `tv_entity` says the TV is off: on through Home Assistant, then
  `back_app` (Frame TV) opened. Also `POST /tv/on`. It works while the add-on is waiting for the sleeping TV.
- Follow the music is a button by "New picture" and the others, lit when it's on, instead of a switch under Settings.
  While the music plays, the line at the top says a picture you choose stays until the next song.
- With the TV off, a new song no longer makes the add-on try the TV again at once; it waits the usual five minutes.
  Each song held up the buttons on the page for a minute or two, so they were greyed out most of the time.

## 0.22.0

- Film and animation: six new categories, Pixar, Disney, Star Wars, Studio Ghibli, DreamWorks and Marvel, with
  backdrops without text from TMDB. They come through Stasera with the new source type `tmdb` (a studio, a film
  series or a show by its TMDB id), so they need the add-on linked to Stasera, and no TMDB key. Options you've saved
  keep their sources: to get the new ones, add the six lines from DOCS.md (Sources) under `sources`.
- "Don't show this picture again" on the add-on's page: the picture on the wall is never drawn again, and another one
  comes. It works for every source, for a backdrop with a logo after all or a picture you don't like. Also `POST /never`.

## 0.21.1

- The device in Home Assistant no longer goes unavailable for a minute and a half every six minutes while the TV is
  off. Connecting to a sleeping TV held up the whole add-on for up to 90 seconds (samsungtvws asks the TV for its model
  with a blocking request), long enough for the MQTT broker to drop the connection.
- Opening the app when Art Mode goes off (`back_app`) no longer stops working after the TV has been asleep: the watcher
  gave up for good the first time the TV didn't answer.

## 0.21.0

- Tonight's show can turn the TV on too, like the morning picture: "Turn the TV on first" under it on the add-on's
  page (on by default; it needs `tv_entity`).
- "Only when someone is home" is for turning the TV on as well as Follow the music, and is a setting of its own on the
  page. Who's home comes from the new option `home_entity` (`zone.home` by default; a person, device_tracker, group,
  binary_sensor or input_boolean works too).
- A morning picture asked for before `morning_time` (or tonight's show before `tonight_time`) no longer counts as the
  day's, so the one at its time still comes. Before, "Morning picture now" after midnight used up the next morning.

## 0.20.1

- The add-on's page, the device in Home Assistant and the options are always in English; `language` is only for the
  morning picture and the posters on the wall. `auto` follows Home Assistant's system language, not the language in
  your profile.
- `tv_host` is empty by default; without it the add-on says so in the log and stops. Saved options keep theirs.
- `back_app` is back as an option, empty by default: the app opened when Art Mode goes off while the TV is on. To
  keep opening Frame TV, set it to `FrameTVapp.FrameTV`.
- New documentation for everyone: a shorter README, and DOCS.md on the add-on's Documentation tab in HA.

## 0.20.0

- English or Norwegian: the morning picture, the posters, the device in Home Assistant and the add-on's page follow
  Home Assistant's language. The new option `language` is `auto` (the default), `en` or `nb`; other languages give
  English. The entity ids stay the same, so automations and dashboards keep working.
- The options have names and help text in HA (`translations/`), and the default sources have English names. Sources
  already saved in your options keep theirs.
- The electricity price follows the sensor's currency: øre and kroner for NOK, otherwise the number with its unit.
- The README and this changelog are in English.
- The Rijksmuseum source works again; since 0.15.0 every picture from it failed.

## 0.19.0

- The add-on's page: if the TV is off (`tv_entity`) when you press a button or choose a picture, the page asks whether
  to turn it on. Then HA turns it on, and the picture comes in Art Mode half a minute later. `GET /tv` says whether the
  TV is off, and `?wake=1` on `/next` and `/show` turns it on first.

## 0.18.0

- The morning picture uses the whole screen, with bigger type. Under the weather are the temperatures at 8, 12, 16 and
  20, the wind from fresh breeze, and "Risk of icy roads" when there's precipitation around zero degrees in the morning.
- The electricity is shown as bars hour by hour, with the cheapest and dearest hours marked. Tibber's price sensor now
  works (`tibber.get_prices`), as well as Nord Pool.

## 0.17.1

- The morning picture: the weather from HA (`weather_entity`, by default `weather.forecast_home`, met.no) and sunrise
  and sunset from `sun.sun`. Without it, or when HA doesn't answer, the picture comes without weather. Open-Meteo and
  `location` are removed.

## 0.17.0

- The morning picture: the weather from HA (`weather_entity`) with Open-Meteo as a fallback (removed again in 0.17.1).

## 0.16.0

- `tmdb_key`, `back_app` and the source type `tmdb` are removed; Stasera gives the film pictures, and Frame TV is always
  the app opened when Art Mode goes off.
- The add-on's page: the switch "Turn the TV on first" under the morning picture is back (on by default). The TV is
  `tv_entity` in the options; without it the switch is grey.

## 0.15.0

- The options in HA have what's set up once: `api_key` (empty: the add-on makes one and writes it in), `location` (a
  place name for the weather; empty: the home in HA), `tv_entity`, `calendars` and `price_entity`. The add-on's page no
  longer shows the key and no longer has the choices for the TV, the calendars and the electricity. If they were chosen
  on the page before, they must go into the options.
- The sources only have `name`, `category`, `type` and `query`. `years`, `shape`, `weight` and `enabled` are ignored:
  everything in the list is included, equally often, from every year. Silent film (which was off) is removed from the
  default list.

## 0.14.0

- Only pictures close to 16:9 (1.45–2.0), cropped to fill the screen. `shape` is ignored, and no pictures are shown
  whole on a blurred background any more. The sources are read again at startup; posters and woodblock prints therefore
  get far fewer pictures.
- The options in HA are only what the add-on needs to start: the TV, Stasera, `tmdb_key`, `back_app` and the sources.
  The interval, the times and the morning picture are on the add-on's page as before, and "Pictures left on the TV"
  (`keep`) has moved there. The weather is for the home in HA, unless `latitude` and `longitude` are in the options.
- The add-on's page: the list of TVs and electricity sensors shows the entity too. "Turn on Art Mode" is gone; the
  other buttons turn it on.

## 0.13.0

- The morning picture: the week and the name day under the date, and on the right today's events from the calendars in
  HA, what's new in Stasera today (episodes and premieres) and the cheapest and dearest hours for electricity. The
  calendars and the electricity sensor are chosen on the add-on's page.
- The screensaver: Frame TV says how often the picture changes (`POST /saver?minutes=`), no longer the interval.

## 0.12.0

- The morning picture can turn the TV on first: choose the TV among the media players in HA on the add-on's page and
  turn on "Turn the TV on first". If it's off, HA turns it on, and the morning picture comes in Art Mode.
- The add-on's page: a line under the title says what's in charge now (Rotation, Fixed picture, Follow the music, the
  morning picture, the screensaver), and the buttons are alike. The category is in front of the source; the version is
  gone.
- "Choose picture" only shows pictures from the sources that are ticked.
- The switch "Screensaver" (`screensaver`, `switch.frame_art_screensaver`): off, and Frame TV starts no screensaver.
  Frame TV reads it from `/status`.

## 0.11.0

- The add-on's page: each source has its own tick, and the rotation draws from those that are ticked. The sources are
  under their category, which ticks all in it at once. The modes Shuffle and Category are gone; what was chosen becomes
  the ticks (`sources_off` in `/data/settings.json`).
- The page is tidied: the buttons together under the picture, the sources in one list, the settings and the connections
  on their own. "Choose picture" opens the pictures under the category.
- Sources that have never been read are read in the background at startup, so the number of pictures is there at once.
- HA: `select.frame_art_mode` is Shuffle or Fixed picture; `select.frame_art_category` ticks only that category.

## 0.10.2

- Follow the music: a restart while music is playing no longer shows the picture from before for a moment.

## 0.10.1

- Follow the music: a new picture for each song, with the song, the artist and the album (when it isn't called the same
  as the song). The player is checked every 4 seconds.
- The add-on's page: the screensaver and Follow the music are no longer "coming", and "next" isn't shown while the
  music is in charge.

## 0.10.0

- Follow the music: when Spotify plays (`media_player.spotify*` in HA, SpotifyPlus too), the album cover comes on the
  wall, big on a surface in the cover's colours, with the album and the artist. One picture per album. Three minutes
  after the music stops, what was there before comes back. It goes in front of everything else; `wanted` can be
  `music`. The switch "Only when someone is home" uses `zone.home`.
- The add-on reads the state in HA (`homeassistant_api`), without a Spotify token of its own. `GET /status` has
  `music`.

## 0.9.1

- `stasera_url` is `https://www.stasera.app` by default. The old address (`https://<deployment>.convex.site`) still
  works. Use www: `stasera.app` redirects there, and the linking doesn't survive that.

## 0.9.0

- The screensaver (`POST /saver`): with "Stasera in the screensaver" on, what we watch and want to start in Stasera
  comes, as posters with the title, in turn with the interval, until Art Mode is turned off. `wanted` can be `saver`.
- Back to Frame TV: if Art Mode goes off while the TV is on (Back or power on the remote), the add-on opens Frame TV.
  The option `back_app` (empty turns it off).
- A picture still on the TV isn't sent again.

## 0.8.1

- The link to Stasera says it's Home Assistant, so it's under Home Assistant on Stasera's Connections page, not as a
  TV. A link from before is a TV until it's linked again.

## 0.8.0

- The API needs a key (the header `Authorization: Bearer …` or `?key=`). The add-on makes it, and the add-on's page
  shows it. The page in HA doesn't need it. Calls without a key, like old `rest_command`s, are refused: use the MQTT
  buttons.
- `POST /saver`: Frame TV's screensaver turns on Art Mode.

## 0.7.0

- Frame Art is a device in Home Assistant over MQTT (Mosquitto): buttons, mode and category, interval, switches, the
  picture showing and what decides now. The connection comes from the Supervisor. Without Mosquitto it runs as before.

## 0.6.1

- A new source type `stasera`: the backdrops of what we watch, the movies and the recommendations in Stasera, without a
  TMDB key. The Film category in the defaults uses it instead of `tmdb`, and `tmdb_key` is no longer there.

## 0.6.0

- Categories: the field `category` on the sources, seven in the defaults. Add it to your own sources (without it the
  category is the source's name).
- Modes on the add-on's page: Shuffle (the categories that are ticked), Category (one) and Fixed picture (choose a
  picture from a category; it stays until the next morning picture).
- What wins is decided in one place: what you choose yourself, then the morning picture and tonight's show, then the
  rotation.
- API: `/settings`, `/category`, `/thumb` and `/show`.

## 0.5.4

- `/status` and the add-on's page show the right version.

## 0.5.3

- A repo of its own, `eaugum/frame-art`: installed and updated from the Add-on Store.

## 0.5.2

- The add-on's page tells a source not read yet from one without pictures.

## 0.5.1

- The link to Stasera says what went wrong.

## 0.5

- The morning picture and tonight's show from Stasera, and the schedule on the add-on's page.

## 0.4

- The sources are a list in the options, with 26 sources: paintings, abstract, Japan, posters, nature, space and film.
