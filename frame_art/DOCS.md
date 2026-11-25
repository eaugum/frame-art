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

## What it needs

Frame Art starts with only `tv_host`. The rest is optional, and each piece adds something.

**From the TV:** a Samsung The Frame, on and on the same network, that has answered **Allow** once.

**From Home Assistant's integrations:**

| Integration | Gives | Used for |
|---|---|---|
| [Mosquitto broker](https://www.home-assistant.io/integrations/mqtt/) add-on and the MQTT integration | The device **Frame Art** | [Buttons, switches and sensors](#in-home-assistant-mqtt). The add-on runs without it |
| Met.no, or another with a `weather.*` entity that gives forecasts | `weather_entity` | The weather on the morning picture |
| Any calendar integration, such as Google Calendar or Local Calendar | `calendars` | Today's events on the morning picture |
| Nord Pool or Tibber | `price_entity` | The electricity price on the morning picture |
| [Wake on LAN](https://www.home-assistant.io/integrations/wake_on_lan/) | `wake_on_lan.send_magic_packet` | Turning the TV on. The add-on can't reach the home network's broadcast itself, so Home Assistant sends the packet, to the MAC address the TV gives on port 8001. Add the integration (`wake_on_lan:` in `configuration.yaml`, or Settings → Devices & services) |
| Spotify or SpotifyPlus | A `media_player.spotify*` | [Follow the music](#follow-the-music) |
| Person, Device tracker or a Zone | `sleep_entity` | Everyone's asleep: a `binary_sensor`, `input_boolean`, `switch` or `group` that is `on` then. It's the night then: the TV goes off from Art Mode, and comes on with the morning picture when it's off. Empty: the night is between tonight's window and the morning window |
| `home_entity` | "Only when someone is home" |

**What the add-on asks Home Assistant for** (in `config.yaml`, nothing to set up):

| Access | Why |
|---|---|
| `services: mqtt:want` | The broker's address and login, when Mosquitto is there |
| `homeassistant_api` | The weather, calendars, price, Spotify player, who's home, the language, and turning the TV on |
| `hassio_api` | Writing the key it makes into its own options (`api_key`) |
| `ingress` | The page in the sidebar |
| `map: media` | Reading your own pictures in `/media`, read-only |
| Port 8099 | The API, for Frame TV and scripts. Turned off under Network on the Configuration tab, Frame TV can't reach it |

**From Stasera:** an account, for tonight's show, the posters and the film sources. See
[Tonight's show](#tonights-show-stasera). The add-on has its own link, separate from Frame TV's.

**From museums and archives:** nothing. No keys are needed, but the add-on needs the internet.

## Options

What's set up once is in the add-on's options. What you change from day to day (which sources are ticked, the
interval, the times and the switches) is on the add-on's page and is saved in `/data/settings.json`.

| Option | What |
|---|---|
| `tv_host` | The TV's IP address |
| `language` | The language of the morning picture and the posters: `auto` (default), `en` or `nb`. See [Language](#language) |
| `api_key` | The key for the API and Frame TV's `art_key`. Left empty, the add-on makes one at its start and writes it in |
| `weather_entity` | The weather for the morning picture, e.g. `weather.forecast_home` (Met.no). Empty gives no weather |
| `home_entity` | Who's home, for "Only when someone is home": `zone.home` (default; someone in it), or a `person`, `device_tracker`, `group`, `binary_sensor` or `input_boolean` that is `home` or `on`. Empty: always home |
| `calendars` | `calendar.*` entities whose events today are shown on the morning picture |
| `price_entity` | A Nord Pool or Tibber price sensor for the morning picture |
| `stasera_url` | [Stasera](https://www.stasera.app), for tonight's show, the screensaver posters and the film sources. Optional |
| `back_app` | The id of a TV app to open when Art Mode is turned off while the TV is on, e.g. a home screen app. Empty (default): none |
| `smartthings_entity` | The TV's `media_player` from Home Assistant's SmartThings integration, for the TV tab's picture mode, sound mode and power. Empty (default): the `media_player` with the TV's name |
| `sources` | Where the pictures come from. See [Sources](#sources) |

## Language

The add-on's page, its device in Home Assistant and the options are in English. The morning picture and the posters on
the wall are in English or Norwegian. With `language: auto` they follow Home Assistant's **system** language (Settings →
System → General), not the language in your user profile; any language other than Norwegian gives English. A change
of language in Home Assistant comes along within ten minutes.

The Norwegian morning picture also shows the day's name day. The electricity price follows the sensor's currency, not
the language: øre and kroner for NOK, otherwise the number with its unit.

## Sources

Everything about where the pictures come from is in the options, in two lists:

- `services`: how a service is asked for pictures, with its address. The add-on comes with some, but none of them is in
  its code.
- `sources`: what you want from them. A source's `type` is the name of a service, or `folder`.

To change them: Settings → Add-ons → Frame Art → Configuration → ⋮ → Edit in YAML. After a restart the add-on's page
shows how many pictures each source found; 0 usually means a wrong name, and the log says which.

```yaml
- name: Abstract                  # shown in front of the title; no colon
  category: Abstract              # several sources can share a category; without it, the category is the name
  type: commons
  query: Paintings by Hilma af Klint|Paintings by Piet Mondrian   # several with |
```

**Removing them:** delete a source from `sources`, and a service from `services` when no source uses it. `sources: []`
and `services: []` remove them all. Leave the lists there, empty: a list that's deleted comes back with the defaults.
A source whose service is gone is left out, and the log says so.

| `type` | What | `query` |
|---|---|---|
| `folder` | The pictures in a folder and its subfolders; the add-on only sees `/media` | The folder, e.g. `/media/frame-art` |
| `met` | The Met, public domain; paintings unless said otherwise | Search words, or fields: `medium=Prints&q=Hiroshige` |
| `rijksmuseum` | The Rijksmuseum, public domain; paintings unless said otherwise | Words in the description (`zee`), or fields: `creator=Vermeer` |
| `nasjonalmuseet` | Paintings from the Nasjonalmuseet in Oslo, through Wikimedia Commons | Artists (`Hans Gude`) |
| `nasjonalbiblioteket` | The National Library of Norway, public domain photos, cropped a little to lose the edges of the negatives; mostly black and white | Search words in Norwegian (`landskap`) |
| `cleveland` | The Cleveland Museum of Art, CC0; paintings unless said otherwise | Search words, or fields: `type=Print&q=Hokusai` |
| `smk` | Statens Museum for Kunst, Copenhagen, public domain paintings | Search words (`landskab`), `*` for everything |
| `commons` | Wikimedia Commons categories, with their subcategories | Category names without `Category:`, e.g. `Featured pictures of Norway` |
| `nasa` | NASA's image library | Search words (`nebula`) |
| `wellcome` | Wellcome Collection, public domain and CC0: old illustrations | Search words (`botanical`) |
| `stasera` | Backdrops of what you watch in Stasera. Needs `stasera_url` and the add-on linked to Stasera | The lists: `watching`, `wantToStart`, `movies` |
| `stasera-recommendations` | Stasera's recommendations, the same way | None |
| `stasera-art` | Backdrops without text from Stasera: up to 5 per film or show. Needs the same | Stasera's ids: `company=3` (a studio's films), `collection=10` (a film series), `tv=82856` (a show), `movie=330459`, `keyword=…`; `&genre=16` narrows a studio down to animation, e.g. `company=3166&genre=16` |

**What fits:** only pictures close to 16:9 are used (from 3:2 to a little wider than 16:9), cropped to fill the
screen. Pictures from the online sources must also be at least 1920 pixels wide. The rest are left out when the source
is read, so sources with mostly portrait pictures, like posters and woodblock prints, give fewer pictures.

**Your own pictures:** Media → Local media → make the folder `frame-art` and upload the pictures there, or copy them to
`/media/frame-art` over Samba. The default source "My pictures" shows them. JPEG and PNG work; HEIC from an iPhone
doesn't. Only files inside the folder are shown; a symbolic link that points outside it is skipped.

**How they're drawn:** every source is drawn equally often, however many pictures it has, and no picture comes again
before 200 others have been shown (or the whole source, if it's smaller). A source is read the first time it's drawn;
sources that have never been read are read in the background when the add-on starts.

**Categories:** the defaults have fourteen: My pictures, Paintings, Old Norway, Abstract, Japan, Posters, Nature and space, Film,
Pixar, Disney, Star Wars, Studio Ghibli, DreamWorks and Marvel. On the add-on's page each category opens to show its sources,
and the tick by a category turns all of its sources on or off.

**Left out:** a picture turned off with "Don't show again" or the × is hidden for good, and one Frame Art can't use
(not close to 16:9, too small, not free) is skipped. After a category's or source's picture count, the page shows
"{n} of {seen} hidden", where `seen` is its pictures shown in the last year plus those hidden, and an opened category
says how many "couldn't be used". Both are counted from 0.44.0; pictures left out before that count in neither.

**Old Norway:** photos from the National Library of Norway, about 1900 to 1950. Options saved before 0.35.0 don't have
them: copy the service `nasjonalbiblioteket` from the add-on's
[config.yaml](https://github.com/eaugum/frame-art/blob/main/frame_art/config.yaml) into `services`, and add this under
`sources`. About a third of what's found has the right shape, and the number on the add-on's page counts them all.

```yaml
- {category: Old Norway, name: Old Norway, type: nasjonalbiblioteket, query: landskap|fjord|panorama|by}
```

**Film and animation:** Pixar, Disney (Walt Disney Animation Studios and the classics), Star Wars (the saga, Rogue One,
Solo and the shows), Studio Ghibli, DreamWorks Animation and Marvel Studios are `stasera-art` sources: backdrops without text
from Stasera, so they need the add-on linked to Stasera. The first time a studio is asked for,
Stasera fetches it in the background, and the pictures come a minute or two later. Options saved before 0.22.0 don't have them; add these under `sources`:

```yaml
- {name: Pixar, type: stasera-art, query: company=3}
- {name: Disney, type: stasera-art, query: company=6125|company=3166&genre=16}
- {name: Star Wars, type: stasera-art,
   query: collection=10|movie=330459|movie=348350|tv=4194|tv=82856|tv=83867|tv=115036|tv=92830|tv=114461}
- {name: Studio Ghibli, type: stasera-art, query: company=10342}
- {name: DreamWorks, type: stasera-art, query: company=521}
- {name: Marvel, type: stasera-art, query: company=420}
```

Official wallpapers and concept art
aren't in Stasera; download them yourself and put them in a folder source in the same category:

```yaml
- {category: Pixar, name: Pixar wallpapers, type: folder, query: /media/frame-art/pixar}
```

The film pictures from Stasera aren't free, but are for use at home. Everything else is public
domain or free to use.

### A service of your own

A service needs an open JSON API that can list pictures, and nothing in the add-on has to change. Add it to `services`
and point a source at it:

```yaml
services:
  - name: cleveland
    url: "https://openaccess-api.clevelandart.org/api/artworks/?type=Painting&has_image=1&cc0=1&limit=100&fields=id,images&q={query}&skip={offset}"
    items: data
    width: images.print.width
    height: images.print.height
    steps:
      - "https://openaccess-api.clevelandart.org/api/artworks/{id}"
    require:
      - step1.data.share_license_status=CC0
    image: "{step1.data.images.print.url}"
    thumb: "{step1.data.images.web.url}"
    title: "{step1.data.title} ({step1.data.creation_date}) | {step1.data.title}"
sources:
  - {name: Cleveland landscapes, category: Paintings, type: cleveland, query: landscape|seascape}
```

A source may also set any of these fields itself, and then they go before the service's. With `type: json` a source
needs no service and has them all itself.

| Field | | |
|---|---|---|
| `url` | Required | The search. `{query}` is each of the source's queries, and `{page}` (from 1) or `{offset}` (from 0) is the next page. A query with `=` in it is fields, which replace the url's own. `{stasera}` is `stasera_url`, asked as the linked add-on; it can be used in `image` and `thumb` too |
| `query` | | The query for a source that has none |
| `accept` | | The `Accept` header, if the API wants something else than JSON |
| `items` | | Where the list is in the answer; empty: the answer is the list. `items.*.backdrops` is every item's backdrops |
| `next` | | The next page's address in the answer, for an API that gives one |
| `pages` | | How many pages per query; 5 if it's left out |
| `pause` | | Seconds between the pages |
| `hours` | | How long the list is kept; 24 if it's left out |
| `wait` | | A field in the answer that means "not ready": it's asked again for up to 90 seconds |
| `id` | | What's kept for a picture: a path, or a text with paths in braces. Without it, the field `id` with `steps`, and otherwise the picture's address |
| `steps` | | Calls per picture, in order. Their answers are `step1`, `step2`... |
| `require` | | What has to be true before a picture is used: `path=value`, or `path~text` for text somewhere in it. This is where a license is checked |
| `unless` | | A field in the query that turns `require` off, like `medium` for a source that isn't paintings |
| `image` | Required | The picture's address |
| `thumb` | | A small copy for the add-on's page. Without `width`, `height` or `ratio` the picture's shape is checked on it before the download |
| `title` | | The text for the picture; without it, the source's name |
| `width`, `height` | | The picture's size, in the list or in `steps`, so the wrong shapes are left out early |
| `ratio` | | The same for an API that gives the shape instead of the size |

`image`, `thumb` and `title` are paths in the list's item and the steps' answers (`images.0.url`, numbers for lists), or
texts with paths in braces. Alternatives are separated with ` | `, and the first that has all its fields counts; for
`image`, the next is also tried if the first isn't there.

In braces, a path can end in `|before:text` (what's before the text), `|year` (the first year), `|file` (a file name
without `File:` and the extension) or `|part:1` (the parts between ` - `, from 0). `?text` in a path is the first in a
list with that text in it: `locations.?iiif-image.url`.

Three things are up to you:

- **The license:** the add-on can't know what's free to use. Ask for it in `url`, check it with `require`, or both.
- **Keys:** an API that needs a key only works with the key in `url`. Then the key is in the add-on's options.
- **Downloads:** a service can answer the search and still refuse to let the add-on download its pictures; the Art
  Institute of Chicago answers 403. The picture is then left out.

## From the remote

In Art Mode the remote's keys open the TV's own menu along the bottom, and the TV says nothing about them. Choosing a
picture there with OK is the one thing Frame Art hears, so it means **New picture**: press right, then OK, and a new
picture from the rotation comes, whichever one you were on. Like "New picture" on the page, it ends a fixed picture.

## The add-on's page

Open **Frame Art** in the sidebar. A line under the title says what's in charge now. From the page you can:

- show a new picture, the morning picture or tonight's show at once,
- turn Follow the music on or off with its button by the others (it's lit when it's on),
- turn the TV on: "Turn the TV on" is there while the TV is off It turns the TV on with Wake-on-LAN
  and opens `back_app` (Frame TV: `FrameTVapp.FrameTV`); without `back_app`, the TV stays where it comes up,
- tick sources and categories,
- **choose a picture**: "Choose picture" in an opened category shows what's been shown lately and 24 at random. The picture
  you press is shown at once and stays until the next morning picture. "New picture" or "Resume the rotation now" ends it
  sooner. The × in a picture's corner leaves it out for good, after a question,
- leave out the picture on the wall for good: "Don't show again" in the picture's corner, then yes to the question
  (a backdrop with a logo after all, or a picture you don't like). Another one comes at once.

The **Settings** tab sets how often the picture changes, how many of Frame Art's pictures stay on the TV, the times for
the morning picture and tonight's show and what the morning picture shows, and the screensaver, and links the add-on
to Stasera. Two more are for the rotation:

- **Don't repeat a picture for** (0 days by default): a picture shown within that many days isn't drawn again while its
  source has others; when they've all been shown, the one shown longest ago comes. With 0, a picture only waits for the
  last 200 changes.
- **Pause the rotation**: the picture on the wall stays. The morning picture, tonight's show, the music and "New
  picture" still work; resumed, the picture gets a whole interval before the next one.

The **TV** tab is in sections (AUG-1728), the ones you need most first. It's read when the tab opens and every minute
while it's open; Art Mode at most every 5 minutes, and only while the TV is on. With the TV off, it shows what was read
last, and when.

- **Now**: whether the TV is on and in Art Mode, the picture it shows or the app in front, the volume and the power it
  draws, with a button that turns it on (with Wake-on-LAN, and then Frame TV opens, as "Turn the TV on" does) or off
  (by holding power, whatever it shows).
- **Art Mode**: the TV's own brightness, colour temperature and motion sensitivity, Sleep After and the light sensor,
  within what the TV says they can be. A change goes to the TV at once and is shown as the TV has it after; it can only
  be made while the TV is on. Then My Photos (how many pictures, and how many are Frame Art's), Samsung's own
  slideshow, and Frame Art's two settings for the TV: "Turn off the TV's own Art Mode timer and light sensor" (Sleep
  After and the light sensor are locked while it's on, since Frame Art turns them off again) and "Turn the TV off when
  nobody is home".

The rest are closed until you open them (the page remembers which), with the gist on the line:

- **Picture and sound**: picture and sound mode and the source, from Home Assistant's SmartThings integration
  (`smartthings_entity`); the volume, asked of the TV itself (UPnP); and the brightness Art Mode has learned you want at
  each light level.
- **Power and energy**: the power it draws (Samsung's TVs often say 0 W, so it's the energy SmartThings reported for
  the last 15 minutes), when it last came on and went off and why, as the TV says (the power button, Art Mode's own
  timer or light sensor...), how long the screen has been on in all, Auto Power Off, energy saving, ambient light
  detection, off without a signal, network standby, the sleep timer and HDMI-CEC.
- **Apps**: the streaming apps it has, in front, running or closed.
- **About the TV**: name, model, firmware, system, memory, storage, network, Wi-Fi signal, language and Developer Mode.

What only the TV itself can read comes from Frame TV (with `art_url` set), when it starts and every hour: the firmware,
Tizen and Chromium versions, memory, storage and the Wi-Fi signal, and, with Frame TV's small service beside it
(`FrameTVService.tpk`), the TV's own power, ECO and HDMI-CEC settings. Nothing on the TV is changed from here but the
Art Mode settings. "Everything the TV said" has the answers as they came.

The **Debug** tab shows a day at a time; ‹ and › go between the days, and "Today" comes back to today. At the top is a timeline: when the TV was on, in
Art Mode, showing Frame TV, the screensaver and the music, and when the morning picture and tonight's show came (striped:
not known). Under it is what the add-on did and what it saw the TV do, newest first: when, what and why (the timer, the
morning picture at 07:00, Home Assistant, Frame TV or the page). A button per source with events that day shows only
that source's; pressed again, or "All", shows them all.
"Export as JSON" downloads all of it. The last 7 days are kept in `/data/events.jsonl`.

The add-on asks the TV every 20 seconds whether it's on, and hears from the TV when Art Mode goes on or off. Only
changes are listed. A change that comes within two minutes of something Frame Art did says what that was; any other
change is marked **from outside**: the remote, the motion sensor, or the TV going to sleep by itself. Frame TV sends its
own events too: started, hidden and shown, what it opened, its screensaver and errors. When the add-on doesn't answer,
they wait on the TV and come later, with the time they happened.

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

In its window (07:00–10:00 every day by default; see [The schedule](#the-schedule)) Frame Art makes a picture of the day, in calm type on a surface coloured by the
weather:

- the weekday and the date, the week number and, in Norwegian, the name day,
- the day's highest and lowest temperature, the weather in words ("Rain from 15:00"), sunrise and sunset, and the
  temperatures at 8, 12, 16 and 20, from `weather_entity` and `sun.sun`,
- the wind when it's at least a fresh breeze, and "Risk of icy roads" when there's precipitation around zero in the
  morning,
- on the right, when there's something to show: today's events from `calendars`, what's new in Stasera today, and the
  electricity price hour by hour as bars, with the cheapest and dearest two hours for the rest of the day.

Each part (the weather, the calendar, the electricity price, the name day and what's new in Stasera) can be turned off
under the morning picture on the Settings tab. Without the weather the surface is grey.

The price works with a Nord Pool sensor (`raw_today` or `today`) or Tibber's price sensor
(`sensor.<home>_electricity_price`), whose prices come from `tibber.get_prices`. Without a weather entity, or if it
doesn't answer, the picture comes without weather.

If the TV isn't on in Art Mode during the window, the picture is made ready for the next time Art Mode comes on, and
whatever is on the screen stays. After the window it's skipped that day.

A morning picture you ask for yourself before its window ("Morning picture now") doesn't count as the day's: the
morning picture still comes in its window.

## Tonight's show (Stasera)

With [Stasera](https://www.stasera.app) linked, Frame Art makes a poster in its window (18:00–23:00 by default) of the
first show in Stasera's "Tonight": the backdrop, the logo or the title, and the season and episode. If there's nothing
tonight, there's no poster.

Tonight's show has its own week and its own "Turn the TV on", like the morning picture's.

## The schedule

Each of the two pictures has a week on the add-on's page: for every day, on or off, and the window from and until.
Within its window the picture stands on the wall; the rotation goes on after it. Around them, Art Mode is on while
someone is home, except at night:

- **The night** is from when tonight's window ends until the morning window starts, by the week's times (also on a day
  a picture is off). With `sleep_entity` in the configuration (an entity that's `on` while everyone's asleep), the
  night is while it's on instead, and tonight's show stands until then.
- **When the night starts,** the TV goes off if it's in Art Mode. If something plays, it's left alone, and the TV goes
  off when it comes back to Art Mode.
- **When the night is over,** the TV comes on with the morning picture if someone is home ("Turn the TV on" under the
  morning picture). Turn the TV on yourself less than two hours before the morning window, or wake
  up then (`sleep_entity`), and the night is over: the morning picture comes at once and stands until its window ends.
- **When a window starts,** the TV comes on if someone is home, also if you turned it off earlier that day ("Turn the
  TV on", per picture). If it's on already, whatever it shows stays.
- **When someone comes home** (`home_entity`), the TV comes on, also at night.
- **Art Mode timer at night** (30 min by default; 0: never): Art Mode turned on at night, by hand or because someone
  came home, goes off after that long.
- **Turn the TV off when nobody is home** (on by default): the TV goes off as soon as `home_entity` says nobody is
  home, also while something plays. It's on the **TV** tab.
- **Turn off the TV's own Art Mode timer and light sensor** (on by default): the TV's "Sleep After" would otherwise put
  it in standby after an hour, and its light sensor within a minute in a dark room (a winter morning at 06:00),
  whatever the schedule says. It's on the **TV** tab, with the TV's own Art Mode settings.

Turned off by hand, the TV stays off until someone comes home, the next window starts or the night is over. If it
doesn't come on (off the network), it's tried three times, five minutes apart. Frame Art turns the TV off by holding
power for three seconds, as Home Assistant does for The Frame.

When the TV goes off or out of Art Mode within 10 minutes of the morning picture or tonight's show, or the picture
came while the TV wasn't in Art Mode, it stays: the rotation counts from when Art Mode is on again, not from when the
picture was put up.

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
| `switch.frame_art_paused` | Pause the rotation |
| `switch.frame_art_screensaver`, `_screensaver_stasera`, `_music` | The screensaver and Follow the music |
| `switch.frame_art_music_home_only` | Only when someone is home: Follow the music (the schedule only turns the TV on when someone is home anyway) |
| `sensor.frame_art_showing` | The picture's title, with the source, the category, when it changed and the next change as attributes |
| `sensor.frame_art_wanted` | What's in charge: `music`, `rotation`, `fixed`, `morning`, `tonight` or `saver` |
| `image.frame_art_picture` | The picture on the wall, 1280 pixels wide |
| `binary_sensor.frame_art_tv_on`, `_art_mode` | Whether the TV is on, and in Art Mode, as the add-on sees it (asked every 20 seconds) |
| `sensor.frame_art_activity` | What the TV does: `off`, `app` (Frame TV or another app), `art`, `morning`, `tonight`, `saver`, `music` or `unknown` |
| `switch.frame_art_tv_power` | The TV on (Wake-on-LAN, then Frame TV) and off (holding power, whatever it shows); its state is `binary_sensor.frame_art_tv_on`'s |
| `number.frame_art_tv_brightness`, `_tv_color_temperature`, `_tv_motion_sensitivity` | The TV's own Art Mode brightness (0–10), colour temperature (−5 to 5) and motion sensitivity (1–3) |
| `select.frame_art_tv_motion_timer` | The TV's Sleep After: Off, 5, 15, 30, 60, 120 or 240 min |
| `switch.frame_art_tv_light_sensor` | The TV's light sensor in Art Mode |
| `switch.frame_art_tv_timer_off` | Keep the TV's Sleep After and light sensor off, so the schedule decides |
| `switch.frame_art_away_off` | Turn the TV off when nobody is home |
| `sensor.frame_art_tv_off_reason` | Why the TV last went off, as it says itself: `POWER_KEY` (the power button), `ART_APP_TO_SUSPEND` (Art Mode's own timer or light sensor) or another of Samsung's. Needs Frame TV's service |

The TV's settings are unavailable while the TV is off, and are read again each time it goes to Art Mode (so a change
in the TV's own menu comes along). Sleep After and the light sensor can't be changed while
`switch.frame_art_tv_timer_off` is on.


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

### Automations

Three examples. All of them use the device above.

```yaml
# Art Mode when everyone has left
- alias: Frame Art - Art Mode when we leave
  triggers:
    - trigger: state
      entity_id: zone.home
      to: "0"
  actions:
    - action: button.press
      target:
        entity_id: button.frame_art_artmode

# Posters from Saturday morning on (until the category is changed again)
- alias: Frame Art - Posters on Saturday
  triggers:
    - trigger: time
      at: "09:00:00"
  conditions:
    - condition: time
      weekday: [sat]
  actions:
    - action: select.select_option
      target:
        entity_id: select.frame_art_category
      data:
        option: Posters

# Follow the music on from the afternoon (a second automation can turn it off at night)
- alias: Frame Art - Follow the music from 17:00
  triggers:
    - trigger: time
      at: "17:00:00"
  actions:
    - action: switch.turn_on
      target:
        entity_id: switch.frame_art_music
```

## Frame TV

Frame TV, a home screen for The Frame, has buttons for Frame Art; the add-on still decides what's on the wall. In Frame
TV's settings:

- `art_url`: Home Assistant's address with port 8099, for example `http://192.168.1.10:8099`,
- `art_key`: `api_key` from the add-on's Configuration tab.

To go back to Frame TV when Art Mode is turned off, set `back_app` to `FrameTVapp.FrameTV`.

## The API

The add-on answers on port 8099 on the local network, for scripts and apps on the TV. Every call needs the key, as
`Authorization: Bearer <key>` or `?key=<key>`; it's `api_key` in the options. The page in the sidebar doesn't need it.
The answers wait for the TV.

| Call | What |
|---|---|
| `GET /status` | What's showing, when it changed and changes next, the mode, the categories, the number of pictures per source, how many of each are hidden, seen or unusable (`left_out`, and `hidden`, `seen` and `unfit` per category) and the settings |
| `GET /tv` | Whether the TV is off (`{"off": true}`), asked of the TV; `null` while Home Assistant doesn't answer |
| `GET /tv/info` | What the TV tab shows, as last read; `?fresh=1` asks the TV first (Art Mode at most every 5 minutes) |
| `POST /tv/settings` | The TV's Art Mode settings, e.g. `{"brightness": 6}` (`brightness`, `color_temperature`, `motion_sensitivity`, `motion_timer`, `brightness_sensor_setting`); answers as `GET /tv/info` |
| `POST /tv/on` | The TV on with Wake-on-LAN through Home Assistant, then `back_app` opened. Doesn't wait for the TV's turn, so it answers while the add-on waits for a sleeping TV |
| `POST /tv/off` | Turns the TV off by holding power, whatever it shows; nothing when it's off already |
| `POST /next` | A new picture now. `?art_mode=1` turns on Art Mode too, `?what=morning` or `?what=tonight` shows that picture, and `?wake=1` turns the TV on first when it's off. Ends a fixed picture |
| `POST /artmode` | Art Mode on, with the picture it has |
| `POST /never` | The picture on the wall is never shown again, and another comes; only for a picture from a source (`showing_key` in `/status`). `?picture=…` is a key from `/category` instead, and the wall only changes if that picture is on it |
| `GET /category?name=Japan` | Recently shown and 24 at random from the category's ticked sources |
| `GET /thumb?key=…` | A small copy of a picture from `/category` |
| `POST /show?key=…` | That picture now, in Art Mode, fixed until the next morning picture |
| `POST /settings` | Changes the settings, with JSON: `sources_off`, `mode`, `interval_minutes`, `keep`, `morning`, `morning_days`, `morning_tv_on`, `tonight`, `tonight_days`, `tonight_tv_on`, `night_timer_minutes`, `away_off`, `tv_timer_off`, `screensaver`, `screensaver_stasera`, `music`, `music_home_only`, `repeat_days` (0–365), `paused`, `morning_weather`, `morning_calendar`, `morning_price`, `morning_names`, `morning_stasera`. A week is seven `{"on", "from", "until"}`, Monday first; `morning_time` and `tonight_time` from before move every day's start |
| `POST /saver` | The screensaver: Art Mode on (see above). `?minutes=5` changes the picture that often meanwhile |
| `POST /stasera/link`, `/stasera/unlink` | Links to Stasera (the code is in `/status` under `pairing`) and unlinks |
| `POST /event` | For Frame TV's events: `{"events": [{"at": <ms>, "kind": "hidden", "detail": "…"}]}`, up to 100 at a time |
| `POST /tv/report` | For Frame TV's report on the TV when it starts and every hour: firmware, Tizen and Chromium versions, memory, storage, Wi-Fi signal, and `settings`, the TV's own settings by their vconf keys |
| `GET /events/export` | All of it, the last 7 days, as a file |
| `GET /events?since=<id>` | What happened, oldest first: `{"events": [{id, at, source, kind, detail, why}], "more": false}`, the newest 2000 after that id (an id is the time in ms). `?until=<id>` for those before one |

Art Mode is turned on with the Art Mode API. If that doesn't take, Frame Art sends one short press of the power key,
but only when the TV has just said it's on and not in Art Mode.

## Troubleshooting

**Where to look:** the add-on's **Log** tab says what it does and why something failed, and the **Debug** tab on the
add-on's page shows the day's events. Every change of picture is in the log.

- **The log says `tv_host is empty`:** set the TV's IP address in the options, and start the add-on again.
- **No Allow prompt on the TV:** the TV has to be on, and on the same network as Home Assistant. The Art Mode channel
  never asks by itself, so Frame Art first connects to the remote control channel (without sending keys) to get the
  prompt. The token it gets is saved in `/data/token.txt`; delete it to ask again.
- **`Art Mode not answering … trying again`:** the TV is off, busy with AirPlay, or not on that address. Frame Art tries
  again every 5 minutes. If the address has changed, give the TV a fixed one in your router.
- **The picture doesn't change:** the rotation waits while the TV is off or out of Art Mode. The add-on's page says so,
  and the Debug tab says when it started waiting, and why. A fixed picture also stays until the next morning picture.
- **The picture changes by itself as well:** the log says `the TV's own slideshow is on`. Turn it off in Art Mode on the
  TV.
- **A source has 0 pictures:** the name or the query is probably wrong; the log says which.
- **The film sources are empty:** the add-on isn't linked to Stasera, or the link is gone (`Stasera no longer takes the
  token`). Press "Link" on the add-on's page. A studio's first pictures take a minute or two.
- **The morning picture has no weather:** check `weather_entity`. The log says `no weather from …`.
- **No calendar or electricity price on the morning picture:** check `calendars` and `price_entity`. They only show when
  there's something today.
- **The TV doesn't turn on:** check that the Wake on LAN integration is added (the log says `couldn't send
  Wake-on-LAN`), and whether "Only when someone is home" stopped it (the log says `nobody home`). The MAC address is
  read from the TV the first time it answers. A TV that has switched off completely, not just to standby, is off the
  network and can't be woken.
- **No device in Home Assistant:** the log says `no broker`. Install Mosquitto, add the MQTT integration, and restart
  the add-on.
- **Follow the music does nothing:** the switch is off by default, and it needs a `media_player.spotify*` that is
  playing. It doesn't turn on Art Mode by itself.
- **An API call answers `wrong or no key`:** use `api_key` from the options, and check the `Authorization` header.
- **Frame TV can't reach the add-on:** open `http://<Home Assistant>:8099/status?key=<api_key>` in a browser. `wrong or
  no key` means `art_key` doesn't match `api_key`. No answer means the add-on isn't running, or port 8099 is turned off
  under Network on the Configuration tab.

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
