# Frame art

Skript for Kunstmodus på The Frame (TQ50LS03B, 2022, Tizen 6.5, 10.1.2.36), via
[NickWaterton/samsung-tv-ws-api](https://github.com/NickWaterton/samsung-tv-ws-api).

**Må kjøres fra 10.1.2-nettet** (samme nett som TV-en, slik Home Assistant står). Fra 10.1.1.x svarer TV-en
`ms.channel.timeOut` med en gang, uten å spørre om tilgang. Første tilkobling fra en ny maskin gir et
«Tillat»-spørsmål på TV-en; tokenet lagres i `token.txt` (gitignorert).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -I scripts/probe.py 10.1.2.36        # leser status, endrer ingenting
.venv/bin/python -I scripts/upload_test.py 10.1.2.36  # laster opp ett testbilde til «Mine bilder»
```

| Skript | Hva |
|---|---|
| `probe.py` | Kunstmodus på/av, gjeldende bilde, lysbildevisning, bildene på TV-en |
| `upload_test.py` | Lager et 4K-testbilde og laster det opp (vises ikke) |
| `remote_probe.py` | Kobler til fjernkontroll-kanalen (gir tilgangsspørsmålet) |
| `raw.py` | Rå WebSocket-test på port 8001/8002, med svartid |

Resultat 24.10.2026: API 4.3.4.0 støttes, opplasting virker (havner i `MY-C0002`).
