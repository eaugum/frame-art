# Endringer

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
