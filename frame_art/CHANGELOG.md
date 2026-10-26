# Endringer

## 0.12.0

- Morgenbildet kan skru på TV-en først: velg TV-en blant mediespillerne i HA på add-on-siden og slå på «Skru på
  TV-en først». Er den av, skrur HA den på, og Morgenbildet kommer i Kunstmodus.
- Add-on-siden: en linje under tittelen sier hva som styrer nå (Rotasjon, Fast bilde, Følg musikken, Morgenbildet,
  Skjermspareren), og knappene er like. Kategorien står foran kilden; versjonen er borte.
- «Velg bilde» viser bare bilder fra kildene som er krysset av.
- Bryteren «Skjermsparer» (`screensaver`, `switch.frame_art_screensaver`): av, og Frame TV starter ingen skjermsparer.
  Frame TV leser den fra `/status`.

## 0.11.0

- Add-on-siden: hver kilde har sin avkrysning, og rotasjonen trekker fra dem som er krysset av. Kildene står under
  kategorien sin, som krysser av alle i den på en gang. Modusene Shuffle og Kategori er borte; det som var valgt, blir
  avkrysningen (`sources_off` i `/data/settings.json`).
- Siden er ryddet: knappene samlet under bildet, kildene i én liste, innstillingene og tilkoblingene for seg.
  «Velg bilde» åpner bildene under kategorien.
- Kilder som aldri er lest, leses i bakgrunnen ved oppstart, så antallet bilder står der med en gang.
- HA: `select.frame_art_mode` er Shuffle eller Fast bilde; `select.frame_art_category` krysser av bare den kategorien.

## 0.10.2

- Følg musikken: en omstart mens musikken spiller viser ikke lenger bildet fra før et øyeblikk.

## 0.10.1

- Følg musikken: et nytt bilde for hver sang, med sangen, artisten og albumet (når det ikke heter det samme som
  sangen). Spilleren sjekkes hvert 4. sekund.
- Add-on-siden: Skjermspareren og Følg musikken står ikke lenger som «kommer», og «neste» vises ikke mens musikken
  styrer.

## 0.10.0

- Følg musikken: når Spotify spiller (`media_player.spotify*` i HA, også SpotifyPlus), kommer albumcoveret på veggen,
  stort på en flate i coverets farger, med albumet og artisten. Ett bilde per album. Tre minutter etter at musikken
  stopper, kommer det som var der før. Det går foran alt annet; `wanted` kan være `music`. Bryteren «Bare når noen er
  hjemme» bruker `zone.home`.
- Add-on-et leser tilstanden i HA (`homeassistant_api`), uten eget Spotify-token. `GET /status` har `music`.

## 0.9.1

- `stasera_url` er `https://www.stasera.app` som standard. Den gamle adressen (`https://<deployment>.convex.site`)
  virker fortsatt. Bruk www: `stasera.app` sender videre dit, og koblingen tåler det ikke.

## 0.9.0

- Skjermspareren (`POST /saver`): med «Stasera i skjermspareren» på kommer det vi ser på og vil begynne på i Stasera, som
  plakater med tittel, på rundgang med intervallet, til Kunstmodus slås av. `wanted` kan være `saver`.
- Tilbake til Frame TV: går Kunstmodus av mens TV-en er på (Tilbake eller av/på på fjernkontrollen), åpner add-on-et
  Frame TV. Valget `back_app` (tom slår det av).
- Et bilde som fortsatt ligger på TV-en, sendes ikke på nytt.

## 0.8.1

- Koblingen til Stasera sier at den er Home Assistant, så den står under Home Assistant på Staseras side
  Tilkoblinger, ikke som en TV. En kobling fra før står som TV til den kobles på nytt.

## 0.8.0

- API-et krever en nøkkel (header `Authorization: Bearer …` eller `?key=`). Add-on-et lager den, og add-on-siden viser
  den. Siden i HA trenger den ikke. Kall uten nøkkel, som gamle `rest_command`-er, avvises: bruk MQTT-knappene.
- `POST /saver`: Frame TV-s skjermsparer slår på Kunstmodus.

## 0.7.0

- Frame Art er en enhet i Home Assistant over MQTT (Mosquitto): knapper, modus og kategori, intervall, brytere,
  bildet som vises og hva som bestemmer nå. Tilkoblingen kommer fra Supervisor. Uten Mosquitto går den som før.

## 0.6.1

- Ny kildetype `stasera`: bakgrunnsbildene av det vi ser på, filmene og anbefalingene i Stasera, uten TMDB-nøkkel.
  Film-kategorien i standardvalgene bruker den i stedet for `tmdb`, og `tmdb_key` er ikke lenger med der.

## 0.6.0

- Kategorier: feltet `category` på kildene, sju i standardvalgene. Legg det til i dine egne kilder (uten det er
  kategorien kildens navn).
- Moduser på add-on-siden: Shuffle (kategoriene som er krysset av), Kategori (én) og Fast bilde (velg et bilde fra en
  kategori; det står til neste Morgenbildet).
- Hva som vinner avgjøres ett sted: det du velger selv, så Morgenbildet og kveldens serie, så rotasjonen.
- API: `/settings`, `/category`, `/thumb` og `/show`.

## 0.5.4

- `/status` og add-on-siden viser riktig versjon.

## 0.5.3

- Eget repo, `eaugum/frame-art`: installeres og oppdateres fra Add-on Store.

## 0.5.2

- Add-on-siden skiller en kilde som ikke er lest ennå fra en uten bilder.

## 0.5.1

- Koblingen til Stasera sier hva som gikk galt.

## 0.5

- Morgenbildet og kveldens serie fra Stasera, og tidsplanen på add-on-siden.

## 0.4

- Kildene er en liste i valgene, med 26 kilder: malerier, abstrakt, Japan, plakater, natur, rommet og film.
