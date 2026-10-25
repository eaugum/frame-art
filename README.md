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
  type: commons
  query: Paintings by Hilma af Klint|Paintings by Piet Mondrian   # flere med |
  shape: any                      # wide (beskjær til 16:9, hopp over resten) eller any (alt, vist helt)
  years: 1800-1930                # bare met, rijksmuseum, cleveland, smk, nasa og tmdb
  weight: 2                       # 1-10: hvor ofte, mot de andre (1)
  enabled: false                  # av, uten å slette den
```

| Type | Hva | `query` |
|---|---|---|
| `folder` | Bildene i en mappe (og undermapper), alle former | Mappa (`/media/frame-art`) |
| `met` | The Met, public domain; malerier om ikke annet er sagt | Søkeord, eller søkets felt: `medium=Prints&q=Hiroshige` |
| `rijksmuseum` | Rijksmuseum (alt med bilde er public domain); malerier om ikke annet er sagt | Ord i beskrivelsen (`zee`), eller felt: `creator=Vermeer` |
| `nasjonalmuseet` | Nasjonalmuseets malerier på Wikimedia Commons | Kunstnere (`Hans Gude`) |
| `cleveland` | Cleveland Museum of Art, CC0; malerier om ikke annet er sagt | Søkeord, eller felt: `type=Print&q=Hokusai` |
| `smk` | Statens Museum for Kunst, København, public domain; malerier om ikke annet er sagt | Søkeord (`landskab`), `*` for alt, eller felt: `keys=*&object_names=tegning` |
| `commons` | Wikimedia Commons-kategorier, med underkategorier to nivåer ned (alt der er fritt) | Kategorinavn uten `Category:`, f.eks. `Featured pictures of Norway` |
| `nasa` | NASAs bildebibliotek, alle former | Søkeord (`nebula`) |
| `wellcome` | Wellcome Collection, public domain og CC0: gamle illustrasjoner, alle former | Søkeord (`botanical`) |
| `tmdb` | Stillbilder fra filmer på TMDB, uten tekst. Trenger `tmdb_key` (samme som Frame TV) | `top_rated`, `popular`, en person (`Christopher Nolan`), eller discover-felt: `with_genres=878` |

Uten `shape` beskjærer museene, Commons og TMDB (bildene må være nær 16:9, 1,3–2,1, og minst 1920 px brede);
mappa, NASA og Wellcome viser alt helt, på en uskarp kopi av seg selv. `any` passer for plakater, tresnitt og
abstrakt. Art Institute of Chicago er ikke med: bildene ligger bak en Cloudflare-sjekk som et skript ikke kommer forbi. Nasjonalmuseets eget
API er nede til v2 kommer, og DigitaltMuseum gir høyst 1200 px, derfor Commons. Europeana, Smithsonian og Harvard
trenger en nøkkel hver og er ikke med ennå. TMDB-bildene er ikke frie, men til bruk hjemme.

Valgene fra 0.3 (`museums`, `met_queries` osv.) virker fortsatt når `sources` mangler, f.eks. i en gammel
`options.json`.

Hver kilde trekkes like ofte (ganger `weight`), uansett hvor mange bilder den har. Ingen bilder kommer igjen før 200 andre har vært
vist (eller hele kilden, om den er mindre).

Byttet: er TV-en i Kunstmodus, vises bildet med en gang; ellers blir det valgt og står klart til neste gang
Kunstmodus slås på, og det som er på skjermen blir stående. Svarer ikke kunst-appen (TV-en av, AirPlay, rett etter at
Kunstmodus slås på), prøver den igjen hvert 5. minutt med det samme bildet, uten å avbryte noe. `keep` (3) er hvor
mange av våre egne bilder som blir liggende på TV-en.

Tilgang: Kunstmodus-kanalen spør aldri om «Tillat», den bare tier uten token. Uten token kobler tjenesten seg derfor
først til fjernkontroll-kanalen (uten å sende taster). Da kommer spørsmålet på TV-en, og tokenet virker for begge.

## Styre den: Home Assistant og Frame TV

Add-on-et svarer på port 8099 på hjemmenettet, uten innlogging (som TV-ens eget API). Svarene venter på TV-en.

| Kall | Hva |
|---|---|
| `GET /status` | Hva som vises, når det ble byttet og når det byttes neste gang |
| `POST /next` | Et nytt bilde nå; `?art_mode=1` setter TV-en i Kunstmodus også |
| `POST /artmode` | Kunstmodus på, med bildet den har |

Kunstmodus slås på med `set_artmode`. Tar ikke det, sendes ett kort trykk på av/på over fjernkontroll-kanalen, men bare
når TV-en nettopp har sagt at den er på og ikke i Kunstmodus. Timeren alene slår aldri på Kunstmodus.

- **Home Assistant:** `homeassistant/packages/frame_tv.yaml` har `rest_command.frame_art_next` og
  `rest_command.frame_art_artmode`, og skriptene «Kunstmodus - Nytt bilde» og «Kunstmodus - Slå på».
- **Frame TV:** `art_url=http://10.1.2.12:8099` i `config.properties`. Flisen på Hjem: OK slår på Kunstmodus, hold OK
  for et nytt bilde.

## I Home Assistant

1. Kopier denne mappa (uten `.venv`, `token.txt` og `scripts`) til `/addons/frame_art` på Pi-en, med Samba- eller
   SSH-add-on-et.
2. Innstillinger → Add-ons → Add-on Store → ⋮ → Se etter oppdateringer. **Frame Art** står under «Local add-ons».
3. Installer, se over valgene og start. Svar «Tillat» på TV-en første gang. Loggen viser hvert bytte.

Egne bilder legges i `/media/frame-art` (Media-mappa i HA, f.eks. over Samba).

## På en Mac eller en annen maskin

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m frameart --config options.json --preview out   # lager 5 bilder i out/, rører ikke TV-en
.venv/bin/python -m frameart --config options.json --once          # bytter bildet én gang
.venv/bin/python -m frameart --config options.json                 # går av seg selv
```

`options.json` har de samme valgene som `config.yaml`. Token, `state.json` og neste bilde havner ved siden av
(`--data` for en annen mappe).

## Prøveskriptene (AUG-1430)

| Skript | Hva |
|---|---|
| `scripts/probe.py` | Kunstmodus på/av, gjeldende bilde, lysbildevisning, bildene på TV-en |
| `scripts/upload_test.py` | Lager et 4K-testbilde og laster det opp (vises ikke) |
| `scripts/remote_probe.py` | Kobler til fjernkontroll-kanalen (gir tilgangsspørsmålet) |
| `scripts/raw.py` | Rå WebSocket-test på port 8001/8002, med svartid |

Resultat 24.10.2026: API 4.3.4.0 støttes, opplasting virker (havner i `MY-C0002`).
