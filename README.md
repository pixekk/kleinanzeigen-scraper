# Kleinanzeigen Scanner

Durchsucht kleinanzeigen.de in festen Intervallen nach definierten Suchen und schickt neue
Treffer per E-Mail. Läuft als Endlos-Loop im Container – kein Cron, kein externer Scheduler.

## Features

- **Alles in der `docker-compose.yml`** konfigurierbar: Suchen, Filter, SMTP. Kein zweites File nötig.
- Mehrere Suchen parallel, jede mit eigenem Intervall (Default 15 Minuten)
- **Mehrere Suchbegriffe pro Suche** (`queries:`) – z. B. drei ThinkCentre-Modelle, eine gemeinsame Mail,
  Duplikate werden herausgefiltert
- Preisrange (`price_min` / `price_max`), zusätzlich direkt als URL-Filter
- VB-Filter: `any` (egal), `only` (nur Verhandlungsbasis), `exclude` (nur Festpreis)
- "Zu verschenken" und Anzeigen ohne Preis getrennt steuerbar
- Keyword-Filter über Titel + **kompletten Anzeigentext**: `all_of`, `any_of`, `none_of`
  (case- und umlautunabhängig). Ohne Keywords wird alles zurückgegeben.
- Umkreissuche (Orts-ID + Radius), Kategorie-Filter, "nur Angebote", gesponserte PRO-Anzeigen ausblenden
- SQLite-Duplikatsschutz: jede Anzeige wird genau einmal gemeldet; optional erneut bei Preissenkung
- Erster Lauf sammelt still (kein Mail-Schwall), danach nur noch echte Neuzugänge
- HTML-Mail mit Bild, Preis, Ort, Zeitpunkt und Direktlink

Ein Kleinanzeigen-Account wird **nicht** benötigt – die Suchergebnisse sind öffentlich abrufbar.

## Schnellstart

1. `.env` aus der Vorlage anlegen und mit den echten Zugangsdaten füllen (landet **nicht** im Repo):

```bash
cp .env.example .env
```

Dann `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` und
`MAIL_TO` eintragen – die Werte deines eigenen Mailservers bzw. Postfachs.

2. `docker-compose.yml` öffnen und im Block `CONFIG_YAML:` die Suchen eintragen. Die
   `smtp:`-Sektion braucht dort nichts weiter, sie verweist bereits auf die `.env`
   (`$${SMTP_HOST}` usw. – das doppelte `$` ist wichtig, siehe [Secrets](#secrets)).
3. Starten:

```bash
docker compose up -d --build
```

4. Logs prüfen:

```bash
docker compose logs -f
```

Für einen weiteren Container die `docker-compose.yml` kopieren (`container_name`,
Volume-Pfad, Suchen anpassen) und eine eigene `.env` daneben anlegen.

### Eigener Mailserver

`SMTP_SECURITY` steuert die Verbindung: `starttls` (meist Port 587), `ssl` (meist Port 465)
oder `none` (Port 25, nur intern/unverschlüsselt). `SMTP_USER`/`SMTP_PASSWORD` sind die
Zugangsdaten des Postfachs, `SMTP_FROM` üblicherweise identisch mit `SMTP_USER`. Mit
`--test-mail` (siehe unten) lässt sich die Konfiguration vor dem produktiven Einsatz prüfen.

Für Gmail als Absender: 2FA am Konto aktivieren, unter `myaccount.google.com/apppasswords`
ein App-Passwort erzeugen und als `SMTP_PASSWORD` eintragen (`SMTP_HOST=smtp.gmail.com`,
`SMTP_PORT=587`, `SMTP_SECURITY=starttls`).

### Ort und Kategorie herausfinden

Suche einmal im Browser mit dem gewünschten Ort/Radius ausführen und die URL ansehen:

```
https://www.kleinanzeigen.de/s-stuttgart/playstation/k0c161l3331r30
                                                       ^^^  ^^^^ ^^
                                              category_id  location_id  radius_km
```

Alternativ die fertige Browser-URL direkt unter `urls:` eintragen – Ort, Kategorie und
Sortierung werden übernommen, Preis- und Keyword-Filter greifen weiterhin.

## Secrets

Die `docker-compose.yml` liegt in einem **öffentlichen** Repo und enthält deshalb keine echten
Zugangsdaten. Sie referenziert stattdessen Variablen aus `.env` (die per `.gitignore` nie
committet wird):

```yaml
    env_file: [.env]
    environment:
      CONFIG_YAML: |
        smtp:
          host: $${SMTP_HOST}
          user: $${SMTP_USER}
          password: $${SMTP_PASSWORD}
```

Das doppelte `$$` ist nötig, damit Compose die Variable beim Einlesen der Datei stehen lässt
und erst der Scanner sie zur Laufzeit einsetzt. Wichtig: `.env` niemals committen, nicht mal
versehentlich – vor jedem `git add` lohnt ein `git status`.

Alternative: `config/searches.yaml` anlegen (Vorlage: `config/searches.example.yaml`),
`CONFIG_YAML` aus der Compose-Datei entfernen und den Ordner mounten:

```yaml
    volumes:
      - ./config:/app/config:ro
      - ./data:/app/data
    environment:
      CONFIG_PATH: /app/config/searches.yaml
```

## Betrieb im Proxmox-LXC

Docker in einem **unprivilegierten** LXC braucht Nesting. Auf dem Proxmox-Host:

```bash
pct set <CTID> -features nesting=1,keyctl=1
```

Danach im Container Docker installieren (`curl -fsSL https://get.docker.com | sh`), das Projekt
nach z. B. `/opt/kleinanzeigen-scanner` legen und `docker compose up -d --build` ausführen.
`restart: unless-stopped` startet den Scanner nach einem Neustart automatisch mit.

Ohne Docker geht es auch direkt mit systemd:

```bash
apt install -y python3-venv && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
CONFIG_PATH=config/searches.yaml .venv/bin/python -m app.main
```

## Nützliche Befehle

Gebaute Such-URLs anzeigen (prüft die Konfiguration, ohne etwas zu laden):

```bash
docker compose run --rm scanner python -m app.main --show-urls
```

SMTP-Einstellungen mit einer Testmail prüfen:

```bash
docker compose run --rm scanner python -m app.main --test-mail
```

Einmal suchen und Treffer nur loggen, statt zu mailen:

```bash
docker compose run --rm scanner python -m app.main --once --dry-run
```

Gespeicherte Anzeigen einer Suche vergessen (`all` für alle):

```bash
docker compose run --rm scanner python -m app.main --reset "ThinkCentre Mini-PC"
```

Tests:

```bash
docker compose run --rm scanner python -m pytest
```

## Konfigurationsreferenz (pro Suche)

| Feld | Default | Bedeutung |
|---|---|---|
| `name` | – | eindeutiger Name, erscheint im Mail-Betreff |
| `query` / `queries` | – | ein Suchbegriff bzw. mehrere Begriffe für dieselbe Suche |
| `url` / `urls` | – | fertige Kleinanzeigen-Such-URLs statt Suchbegriffen |
| `category_id` | – | Kategorie aus der URL (`k0c161`), auch ohne Suchbegriff nutzbar |
| `enabled` | `true` | Suche vorübergehend abschalten |
| `interval_minutes` | `15` | Abstand zwischen zwei Läufen (min. 5) |
| `recipients` | global | Empfänger nur für diese Suche |
| `price_min` / `price_max` | – | Preisrange in Euro |
| `price_filter_in_url` | `true` | Preisrange zusätzlich als URL-Filter setzen |
| `negotiable` | `any` | `any` / `only` (nur VB) / `exclude` (nur Festpreis) |
| `include_without_price` | `false` | Anzeigen ohne Preisangabe trotz Preisrange melden |
| `include_free` | `true` | "Zu verschenken" immer mitnehmen |
| `location_id` / `radius_km` | – | Umkreissuche |
| `only_offers` | `true` | Gesuche ausblenden |
| `exclude_sponsored` | `true` | gesponserte PRO-/Händleranzeigen ausblenden |
| `keywords.all_of` | `[]` | alle Begriffe müssen vorkommen |
| `keywords.any_of` | `[]` | mindestens einer muss vorkommen |
| `keywords.none_of` | `[]` | keiner darf vorkommen |
| `fetch_details` | `false` | zusätzlich die Anzeigenseite laden (siehe Hinweise) |
| `max_pages` | `1` | Ergebnisseiten pro Suchbegriff (ca. 25 Anzeigen je Seite) |
| `max_new_per_run` | `25` | Obergrenze der Treffer pro Mail |
| `seed_on_first_run` | `true` | erster Lauf ohne Mail |
| `notify_on_price_drop` | `false` | bekannte Anzeige erneut melden, wenn der Preis sinkt |

## Struktur

```
app/
  main.py       CLI + Endlos-Loop mit Scheduler und Signal-Handling
  runner.py     Ablauf einer Suche: laden, filtern, speichern, mailen
  scraper.py    URL-Bau und HTML-Parsing
  fetcher.py    HTTP-Client mit Throttling, Retry und Block-Erkennung
  filters.py    Preis-, VB- und Keyword-Logik
  storage.py    SQLite (gesehene Anzeigen, Laufzustand)
  notifier.py   SMTP-Versand, HTML- und Text-Mail
  config.py     YAML aus CONFIG_YAML oder Datei laden und validieren
config/searches.example.yaml
tests/          Unit-Tests inkl. Fixture einer echten Ergebnisseite
```

## Hinweise

- Die Suchergebnisliste enthält bereits den vollständigen Anzeigentext, deshalb greifen
  Keyword-Filter ohne Zusatz-Request. `fetch_details: true` lädt zusätzlich die Anzeigenseite –
  nur nötig, wenn Kleinanzeigen den Text in der Liste einmal kürzen sollte.
- Das Intervall ist bewusst auf mindestens 5 Minuten begrenzt, zwischen einzelnen Requests
  liegen 3–4,5 Sekunden Pause. Bei HTTP 403/429 pausiert der Scanner die betroffene Suche bis
  zum nächsten Intervall und protokolliert das.
- Mehrere `queries` bedeuten mehrere Requests pro Lauf (ein Request je Begriff und Seite).
- Ändert Kleinanzeigen sein HTML, sind die Extraktoren in `app/scraper.py` die einzige
  anzupassende Stelle; `tests/fixtures/srp_sample.html` enthält eine echte Ergebnisseite als
  Referenz, `tests/test_scraper.py` prüft altes und aktuelles Markup.
