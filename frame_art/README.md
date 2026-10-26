# Frame Art

Vår egen rotasjon i Kunstmodus på The Frame (TQ50LS03B, 2022, Tizen 6.5, 10.1.2.36), i stedet for Samsung Art Store
(AUG-1438). Den bytter bildet av seg selv med et fast intervall, til et tilfeldig bilde fra en tilfeldig kilde som er
slått på, og rydder sine egne gamle bilder i «Mine bilder». Andre bilder der rører den aldri. Den bruker
[NickWaterton/samsung-tv-ws-api](https://github.com/NickWaterton/samsung-tv-ws-api).

Den kjører som et lokalt add-on i Home Assistant OS på Pi-en (10.1.2.12), men trenger ingenting fra HA. Den kan
like gjerne kjøres med Python på hva som helst som står på hjemme.

**Må kjøres fra 10.1.2-nettet** (samme nett som TV-en). Fra 10.1.1.x svarer TV-en `ms.channel.timeOut` med en gang,
uten å spørre om tilgang. Første tilkobling fra en ny maskin gir et «Tillat»-spørsmål på TV-en, så TV-en må være på
da; tokenet lagres i `token.txt` (gitignorert).

## Kildene

Kildene er en liste i valgene (`sources`), så en ny kilde er noen linjer i Home Assistant: Innstillinger → Add-ons →
Frame Art → Konfigurasjon → ⋮ → Rediger i YAML. Etter en omstart viser add-on-ets side hvor mange bilder hver kilde
fant; 0 betyr som regel et feil navn (loggen sier hvilket).

```yaml
- name: Abstrakt                  # vises foran tittelen; uten kolon
  category: Abstrakt              # flere kilder kan dele en kategori; uten den er kategorien navnet
  type: commons
  query: Paintings by Hilma af Klint|Paintings by Piet Mondrian   # flere med |
  years: 1800-1930                # bare met, rijksmuseum, cleveland, smk, nasa og tmdb
  weight: 2                       # 1-10: hvor ofte, mot de andre (1)
  enabled: false                  # av, uten å slette den
```

| Type | Hva | `query` |
|---|---|---|
| `folder` | Bildene i en mappe (og undermapper) | Mappa (`/media/frame-art`) |
| `met` | The Met, public domain; malerier om ikke annet er sagt | Søkeord, eller søkets felt: `medium=Prints&q=Hiroshige` |
| `rijksmuseum` | Rijksmuseum (alt med bilde er public domain); malerier om ikke annet er sagt | Ord i beskrivelsen (`zee`), eller felt: `creator=Vermeer` |
| `nasjonalmuseet` | Nasjonalmuseets malerier på Wikimedia Commons | Kunstnere (`Hans Gude`) |
| `cleveland` | Cleveland Museum of Art, CC0; malerier om ikke annet er sagt | Søkeord, eller felt: `type=Print&q=Hokusai` |
| `smk` | Statens Museum for Kunst, København, public domain; malerier om ikke annet er sagt | Søkeord (`landskab`), `*` for alt, eller felt: `keys=*&object_names=tegning` |
| `commons` | Wikimedia Commons-kategorier, med underkategorier to nivåer ned (alt der er fritt) | Kategorinavn uten `Category:`, f.eks. `Featured pictures of Norway` |
| `nasa` | NASAs bildebibliotek | Søkeord (`nebula`) |
| `wellcome` | Wellcome Collection, public domain og CC0: gamle illustrasjoner | Søkeord (`botanical`) |
| `stasera` | Bakgrunnsbildene (uten tekst når de finnes) av det vi ser på i Stasera. Trenger `stasera_url` og at add-on-et er koblet til Stasera; ingen TMDB-nøkkel | Listene: `watching`, `wantToStart`, `movies`, `recommendations` |
| `tmdb` | Stillbilder fra filmer på TMDB, uten tekst. Trenger en egen `tmdb_key`; `stasera` gjør det samme uten | `top_rated`, `popular`, en person (`Christopher Nolan`), eller discover-felt: `with_genres=878` |

Bare bilder nær 16:9 brukes (fra 3:2 til litt bredere enn 16:9, 1,45–2,0), beskåret så de fyller skjermen; fra
museene, Commons, NASA, Wellcome, Stasera og TMDB må de også være minst 1920 px brede. Resten tas ikke med når kilden
leses, og et bilde i mappa som ikke passer, hoppes over og kommer ikke igjen. `shape` fra før 0.14 overses. Kilder med
mest stående bilder (plakater, tresnitt) får derfor få bilder. Art Institute of Chicago er ikke med: bildene ligger bak en Cloudflare-sjekk som et skript ikke kommer forbi. Nasjonalmuseets eget
API er nede til v2 kommer, og DigitaltMuseum gir høyst 1200 px, derfor Commons. Europeana, Smithsonian og Harvard
trenger en nøkkel hver og er ikke med ennå. TMDB-bildene (også de fra Stasera) er ikke frie, men til bruk hjemme.

Valgene fra 0.3 (`museums`, `met_queries` osv.) virker fortsatt når `sources` mangler, f.eks. i en gammel
`options.json`.

Hver kilde trekkes like ofte (ganger `weight`), uansett hvor mange bilder den har. Ingen bilder kommer igjen før 200 andre har vært
vist (eller hele kilden, om den er mindre).

Byttet: er TV-en i Kunstmodus, vises bildet med en gang; ellers blir det valgt og står klart til neste gang
Kunstmodus slås på, og det som er på skjermen blir stående. Svarer ikke kunst-appen (TV-en av, AirPlay, rett etter at
Kunstmodus slås på), prøver den igjen hvert 5. minutt med det samme bildet, uten å avbryte noe. Hvor mange av våre
egne bilder som blir liggende på TV-en (3), står på add-on-siden.

Tilgang: Kunstmodus-kanalen spør aldri om «Tillat», den bare tier uten token. Uten token kobler tjenesten seg derfor
først til fjernkontroll-kanalen (uten å sende taster). Da kommer spørsmålet på TV-en, og tokenet virker for begge.

## Kildene og kategoriene

Rotasjonen trekker fra kildene som er krysset av på add-on-siden, med `weight` som før. Hver kilde står under
kategorien sin (`category`); standardvalgene har sju: Mine bilder, Malerier, Abstrakt, Japan, Plakater, Natur og
rommet og Film. Krysset ved en kategori slår alle kildene i den av eller på.

En kilde leses (listen over bildene hentes) første gang den trekkes, og alle som aldri er lest, leses i bakgrunnen
når add-on-et starter.

**Fast bilde:** «Velg bilde» ved en kategori viser det som er vist nylig og 24 tilfeldige, fra kildene i den som er
krysset av. Et bilde du trykker på,
vises med en gang og står til neste Morgenbildet; så går rotasjonen videre. «Nytt bilde», en ny avkrysning eller
«Fortsett rotasjonen nå» avslutter det før.

Avkrysningen lagres i `/data/settings.json` (`sources_off`), som tidsplanen.

**Hva som vinner**, øverst først. Når den øverste er ferdig, tar den neste over.

1. Følg musikken, når den er på og det spilles musikk
2. Det du velger selv: et fast bilde, eller «Nytt bilde»
3. Morgenbildet og kveldens serie. Et fast bilde avsluttes av Morgenbildet, ikke av kveldens serie.
4. Skjermspareren
5. Vanlig rotasjon, i modusen

## Morgenbildet og kveldens serie (AUG-1447)

To bilder lager add-on-et selv, én gang om dagen hver, så snart klokka er der. Etterpå går rotasjonen videre som før.

- **Morgenbildet** (`morning_time`, 07:00): ukedag, dato, dagens høyeste og laveste temperatur, været i ord («regn fra
  kl. 15») og sola opp og ned, i rolig skrift på en flate med farge etter været. Været kommer fra Open-Meteo for
  hjemmet i HA (eller `latitude`/`longitude` i valgene). Svarer ikke Open-Meteo, kommer bildet uten vær. Under datoen står uka og
  navnedagen (Almanakkforlagets liste, revidert desember 2025, i `navnedager.json`; `scripts/navnedager.py` lager den
  på nytt). Til høyre, når de har noe:
  - **I dag:** avtalene fra kalenderne du krysser av på add-on-siden (`morning_calendars`, fra HA).
  - **Nytt i Stasera:** nye episoder, sesong- og seriepremierer og filmpremierer i dag (`/tv/upcoming`).
  - **Strøm:** de billigste og dyreste to timene resten av dagen, fra en Nord Pool-sensor i HA med `raw_today` eller
    `today` (`price_entity`).
- **Kveldens serie** (`tonight_time`, 18:00): en plakat av den første i Staseras «I kveld», med bakgrunnsbildet uten
  tekst, logoen (eller tittelen) og sesong og episode. Trenger `stasera_url` og at add-on-et er koblet til Stasera.
  Er det ingenting i kveld, blir det ingen plakat.

Er TV-en av når tiden kommer, venter bildet til den er på igjen, men Morgenbildet bare til kveldens tid. Får den ikke
laget bildet (nettet), prøver den igjen om 15 minutter.

**Skru på TV-en først:** på add-on-siden, under Morgenbildet, velges TV-en blant mediespillerne i HA (`tv_entity`,
f.eks. `media_player.stue_the_frame_stue`). Er den av når Morgenbildet skal komme, skrur HA den på
(`media_player.turn_on`, én gang om dagen), og Morgenbildet kommer i Kunstmodus.

## Skjermspareren og veien tilbake (AUG-1494)

Når Frame TV-s skjermsparer starter (`POST /saver`), slår add-on-et på Kunstmodus. Med «Skjermsparer» av
(`screensaver`, `switch.frame_art_screensaver`) starter Frame TV ingen skjermsparer; den leser valget fra `/status`. Med «Stasera i skjermspareren» på
(`screensaver_stasera`) kommer så det vi ser på og vil begynne på i Stasera, som plakater med «SER PÅ» eller «VIL
BEGYNNE PÅ», tittelen (eller logoen) og neste episode, på rundgang med intervallet. Uten det, eller uten Stasera: vanlig
rotasjon. Et fast bilde, Morgenbildet og kveldens serie går foran. Et bilde som fortsatt ligger på TV-en, velges der i
stedet for å sendes på nytt.

Skjermspareren varer til Kunstmodus slås av. En tast på fjernkontrollen i Kunstmodus (Tilbake, av/på) gir TV-ens egen
Kunstmodus-meny, som bare har veien Hjem → appen. Add-on-et lytter derfor på kunst-kanalen: går Kunstmodus av mens TV-en
er på, åpner den `back_app` (`FrameTVapp.FrameTV`) over TV-ens REST-API på port 8001. Det gjelder hver gang, ikke bare
etter skjermspareren. `back_app: ""` i valgene slår det av; en annen app-id åpner den i stedet.

**Tidsplanen på add-on-siden:** hvor ofte bildet byttes, og av/på og klokkeslett for de to bildene. Det virker med en
gang, uten omstart, og lagres i `/data/settings.json`, foran valgene i add-on-et.

**Stasera:** «Koble til Stasera» på add-on-siden gir en kode og en lenke; godkjenn den i Stasera, som når TV-en kobles.
Tokenet ligger i `/data/stasera_token.txt`. «Koble fra» glemmer det.

## Følg musikken (AUG-1495)

Med «Følg musikken» på (`music`, av som standard) kommer albumcoveret på veggen når Spotify spiller: stort, på en
flate i coverets farger, med sangen, artisten og albumet. Spilleren leses fra Home Assistant (`homeassistant_api`), så det
trengs ingen Spotify-nøkkel her, bare Spotify- eller SpotifyPlus-integrasjonen i HA: den første
`media_player.spotify*` som spiller. Bildet byttes for hver sang, 10–20 sekunder etter at den begynner.

Det går foran alt annet, også et fast bilde, men slår ikke på Kunstmodus selv. Tre minutter etter at musikken
stopper (pause, stopp) kommer bildet som var der før. Har Morgenbildet eller kveldens serie fått sin tid i mellomtiden,
kommer det i stedet. «Bare når noen er hjemme» (`music_home_only`) følger musikken bare når `zone.home` har noen i
seg; uten den følges all avspilling på kontoen. Utenfor HA trenger den `ha_url` og `ha_token` i valgene.

## Styre den: Home Assistant og Frame TV

Add-on-et svarer på port 8099 på hjemmenettet. Hvert kall trenger nøkkelen, som `Authorization: Bearer <nøkkel>` eller
`?key=<nøkkel>`: add-on-et lager den selv, og add-on-siden i HA viser den under «Frame TV». Siden i HA trenger den
ikke. Svarene venter på TV-en.

| Kall | Hva |
|---|---|
| `GET /status` | Hva som vises, når det ble byttet og når det byttes neste gang, modusen (`mode`: `shuffle` eller `fixed`), kategoriene, antall bilder per kilde (`pools`, `null` før den er lest) og valgene |
| `POST /next` | Et nytt bilde nå; `?art_mode=1` setter TV-en i Kunstmodus også, `?what=morning` viser Morgenbildet og `?what=tonight` kveldens serie. Avslutter et fast bilde |
| `POST /artmode` | Kunstmodus på, med bildet den har |
| `GET /category?name=Japan` | Nylig vist og 24 tilfeldige fra kildene i kategorien som er krysset av, til å velge et bilde |
| `GET /players` | Mediespillerne i HA, til å velge TV-en (`tv_entity`) |
| `GET /calendars`, `/prices` | Kalenderne og prissensorene i HA, til Morgenbildet (`morning_calendars`, `price_entity`) |
| `GET /thumb?key=…` | Et lite bilde av en nøkkel fra `/category` |
| `POST /show?key=…` | Det bildet nå, i Kunstmodus, som fast bilde til neste Morgenbildet |
| `POST /settings` | Endrer valgene, med JSON: `sources_off` (kildene som ikke er krysset av), `mode` (`shuffle` avslutter et fast bilde; `category` med `category` krysser av bare den kategorien), `interval_minutes`, `keep`, `morning`, `morning_time`, `tonight`, `tonight_time`, `screensaver`, `screensaver_stasera`, `music`, `music_home_only`, `morning_tv_on`, `tv_entity`, `morning_calendars`, `price_entity`. `/schedule` er det samme |
| `POST /saver` | Frame TV-s skjermsparer startet: Kunstmodus på, og Stasera-bildene til Kunstmodus slås av (se over). `?minutes=5` bytter bildet så ofte i mellomtiden (valget står i Frame TV) |
| `POST /stasera/link`, `/stasera/unlink` | Kobler til Stasera (koden står i `/status` under `pairing`) og fra |

Kunstmodus slås på med `set_artmode`. Tar ikke det, sendes ett kort trykk på av/på over fjernkontroll-kanalen, men bare
når TV-en nettopp har sagt at den er på og ikke i Kunstmodus. Timeren alene slår aldri på Kunstmodus.

- **Home Assistant:** enheten over MQTT (se over); skript og automasjoner trykker på knappene, f.eks.
  `button.press` på `button.frame_art_next`.
- **Frame TV:** `art_url=http://10.1.2.12:8099` og `art_key=<nøkkelen>` i `config.properties`. Flisen på Hjem: OK slår
  på Kunstmodus, hold OK for et nytt bilde. Når skjermspareren starter, sier den fra med `POST /saver`.

## Som enhet i Home Assistant (MQTT)

Med Mosquitto broker-add-on-et og MQTT-integrasjonen i HA melder Frame Art seg inn selv som enheten **Frame Art**;
tilkoblingen kommer fra Supervisor, uten noe i valgene. Uten Mosquitto går add-on-et som før.

| Entitet | Hva |
|---|---|
| `button.frame_art_next`, `_morning_now`, `_tonight_now`, `_artmode` | Neste bilde, Morgenbildet nå, kveldens serie nå, Kunstmodus på |
| `select.frame_art_mode` | Shuffle eller Fast bilde (det som vises nå står til neste Morgenbildet) |
| `select.frame_art_category` | Kategoriene fra kildene; å velge en krysser av bare kildene i den |
| `number.frame_art_interval` | Minutter mellom byttene |
| `switch.frame_art_morning`, `_tonight` | Morgenbildet og kveldens serie |
| `switch.frame_art_screensaver`, `_screensaver_stasera`, `_music`, `_music_home_only` | Skjermspareren og Følg musikken |
| `sensor.frame_art_showing` | Tittelen på bildet; kilde, kategori, når det ble byttet og neste bytte som attributter |
| `sensor.frame_art_wanted` | Hva som bestemmer nå: `music`, `rotation`, `fixed`, `morning`, `tonight` eller `saver` |
| `image.frame_art_picture` | Bildet på veggen, 1280 px bredt |

Tilstanden sendes når den endrer seg (fra HA, add-on-siden eller timeren). En ny kategori i kildene kommer med i
velgeren etter en omstart av add-on-et. Et kort for dashbordet:

```yaml
type: vertical-stack
cards:
  - type: picture-entity
    entity: image.frame_art_picture
    name: Kunstmodus
  - type: entities
    entities:
      - sensor.frame_art_showing
      - select.frame_art_mode
      - select.frame_art_category
      - button.frame_art_next
      - button.frame_art_artmode
```

## I Home Assistant

1. Innstillinger → Add-ons → Add-on Store → ⋮ → Repositories → legg til `https://github.com/eaugum/frame-art`.
2. **Frame Art** står under «Frame Art». Installer (Pi-en bygger den selv, det tar noen minutter), se over valgene
   og start. Svar «Tillat» på TV-en første gang. Loggen viser hvert bytte.
3. En ny versjon her gir «Oppdatering tilgjengelig» i HA (⋮ → Se etter oppdateringer for å se den med en gang).

**Egne bilder:** Media → Lokale medier → lag mappa `frame-art` og last opp bildene der (eller kopier dem til
`/media/frame-art` over Samba). Kilden `type: folder` med `query: /media/frame-art` viser dem. JPEG og PNG går fint; HEIC fra iPhone leses ikke.

## På en Mac eller en annen maskin

```bash
cd frame_art
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m frameart --config options.json --preview out   # lager 5 bilder i out/, rører ikke TV-en
.venv/bin/python -m frameart --config options.json --preview out --what morning   # bare Morgenbildet (eller tonight)
.venv/bin/python -m frameart --config options.json --once          # bytter bildet én gang
.venv/bin/python -m frameart --config options.json                 # går av seg selv
```

`options.json` har de samme valgene som `config.yaml`. Token, `state.json` og neste bilde havner ved siden av
(`--data` for en annen mappe).

## Prøveskriptene (AUG-1430)

| Skript | Hva |
|---|---|
| `../scripts/probe.py` | Kunstmodus på/av, gjeldende bilde, lysbildevisning, bildene på TV-en |
| `../scripts/upload_test.py` | Lager et 4K-testbilde og laster det opp (vises ikke) |
| `../scripts/remote_probe.py` | Kobler til fjernkontroll-kanalen (gir tilgangsspørsmålet) |
| `../scripts/raw.py` | Rå WebSocket-test på port 8001/8002, med svartid |

Resultat 24.10.2026: API 4.3.4.0 støttes, opplasting virker (havner i `MY-C0002`).
