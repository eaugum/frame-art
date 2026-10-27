# Frame Art

**Your Samsung The Frame, curated by Home Assistant.** Frame Art turns Art Mode into a living gallery: museum
masterpieces, Japanese woodblock prints, vintage posters, deep space from NASA and your own photos, changing by
themselves through the day. No Art Store subscription, no phone app, no uploading by hand.

[![Add the repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Feaugum%2Fframe-art)

## What it does

- **Thousands of free artworks, ready to go.** Public domain collections from The Met, the Rijksmuseum, the Cleveland
  Museum of Art, Statens Museum for Kunst, the Nasjonalmuseet, Wellcome Collection, Wikimedia Commons and NASA, sorted
  into categories such as Paintings, Abstract, Japan, Posters and Nature and space. A new source is a few lines.
- **Made for the screen.** Only pictures close to 16:9 are used, cropped to fill the frame, and those from the
  collections are at least Full HD. Nothing ends up letterboxed or blurry.
- **Your own pictures.** Put photos in a folder in Home Assistant's media, and they join the rotation.
- **A morning picture.** At a time you choose, the wall shows the date, the day's weather, sunrise and sunset, today's
  calendar events and the electricity price hour by hour (Nord Pool or Tibber). It can turn the TV on first.
- **Follow the music.** When Spotify plays, the album cover fills the wall in the cover's colours, with the song and
  the artist. When the music stops, the art comes back.
- **A real Home Assistant device.** Buttons, switches, the mode, the category, the interval and the picture on the wall
  are entities over MQTT, ready for automations and dashboards.
- **A page of its own** in the Home Assistant sidebar: tick the sources you want, choose a picture to keep on the wall,
  and set how often it changes.
- **Tidy.** Frame Art cleans up its own old pictures on the TV and never touches the rest of "My Photos".
- **English or Norwegian** on the wall, following Home Assistant's language.

## Requirements

- A Samsung The Frame with Art Mode. Frame Art is developed on the 2022 model; other years with the same Art Mode API
  should work.
- Home Assistant OS or Supervised, on the same local network as the TV.
- Optional: the Mosquitto broker for the device in Home Assistant, a weather integration such as Met.no for the morning
  picture, and the Spotify integration for Follow the music.

## Getting started

1. Press the button above, or in Home Assistant go to Settings → Add-ons → Add-on Store → ⋮ → Repositories and add
   `https://github.com/eaugum/frame-art`.
2. Install **Frame Art**, enter your TV's IP address in the options, and start it.
3. Have the TV on, and answer **Allow** when it asks the first time.
4. Open **Frame Art** in the sidebar and tick what you'd like to see.

Everything else, from the options and the source types to the API, is in the [documentation](frame_art/DOCS.md), which
is also on the add-on's Documentation tab in Home Assistant.

## Credits

Frame Art talks to the TV with [samsung-tv-ws-api](https://github.com/NickWaterton/samsung-tv-ws-api) by Nick
Waterton. The artworks belong to the museums and archives that share them; Frame Art only uses pictures marked as
public domain or free to use, except for the optional film pictures from Stasera, which are for use at home.

Frame Art is not affiliated with Samsung.
