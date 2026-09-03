# Kleinanzeigen Scanner

Polls kleinanzeigen.de at fixed intervals for a set of configured searches and emails you
new matches. Runs as an endless loop inside the container – no cron, no external scheduler.

## Features

- **Everything configurable in `docker-compose.yml`**: searches, filters, SMTP. No second file needed.
- Multiple searches in parallel, each with its own interval (default 15 minutes)
- **Multiple search terms per search** (`queries:`) – e.g. several model variants, one shared mail,
  duplicates are filtered out
- Price range (`price_min` / `price_max`), also applied directly as a URL filter
- Negotiable-price filter: `any`, `only` (negotiable only), `exclude` (fixed price only)
- "Free to a good home" and listings without a price handled separately
- Keyword filter over title + **full listing text**: `all_of`, `any_of`, `none_of`
  (case- and umlaut-insensitive). Returns everything when no keywords are set.
- Radius search (location ID + radius), category filter, "offers only", hide sponsored PRO listings
- SQLite dedup: every listing is reported exactly once; optionally again on a price drop
- First run collects silently (no flood of mail), only real new listings afterwards
- HTML mail with image, price, location, timestamp and direct link

No Kleinanzeigen account is needed – the search results are publicly available.

## Quick start

1. Create `.env` from the template and fill in your real credentials (never lands in the repo):

```bash
cp .env.example .env
```

Then set `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` and
`MAIL_TO` to the values of your own mail server / mailbox.

2. Open `docker-compose.yml` and add your searches inside the `CONFIG_YAML:` block. The
   `smtp:` section doesn't need anything further there, it already refers to `.env`
   (`$${SMTP_HOST}` etc. – the doubled `$` is important, see [Secrets](#secrets)).
3. Start it:

```bash
docker compose up -d --build
```

4. Check the logs:

```bash
docker compose logs -f
```

For an additional container, copy `docker-compose.yml` (adjust `container_name`,
volume path, searches) and place a separate `.env` next to it.

### Using your own mail server

`SMTP_SECURITY` controls the connection: `starttls` (usually port 587), `ssl` (usually port 465)
or `none` (port 25, internal/unencrypted only). `SMTP_USER`/`SMTP_PASSWORD` are the mailbox
credentials, `SMTP_FROM` is usually the same as `SMTP_USER`. Use `--test-mail` (see below) to
verify the configuration before relying on it.

For Gmail as the sender: enable 2FA on the account, generate an app password at
`myaccount.google.com/apppasswords` and use it as `SMTP_PASSWORD` (`SMTP_HOST=smtp.gmail.com`,
`SMTP_PORT=587`, `SMTP_SECURITY=starttls`).

### Finding location and category IDs

Run a search once in the browser with the desired location/radius and look at the URL:

```
https://www.kleinanzeigen.de/s-stuttgart/fahrrad/k0c161l3331r30
                                                   ^^^  ^^^^ ^^
                                          category_id  location_id  radius_km
```

Alternatively, put the finished browser URL directly under `urls:` – location, category and
sorting are taken from it, price and keyword filters still apply.

## Secrets

`docker-compose.yml` lives in a **public** repo, so it doesn't contain any real credentials.
It references variables from `.env` instead (which is never committed, via `.gitignore`):

```yaml
    env_file: [.env]
    environment:
      CONFIG_YAML: |
        smtp:
          host: $${SMTP_HOST}
          user: $${SMTP_USER}
          password: $${SMTP_PASSWORD}
```

The doubled `$$` is needed so Compose leaves the variable alone when reading the file, and only
the scanner substitutes it at runtime. Important: never commit `.env`, not even by accident –
running `git status` before every `git add` is worth it.

Alternative: create `config/searches.yaml` (template: `config/searches.example.yaml`),
remove `CONFIG_YAML` from the compose file and mount the folder instead:

```yaml
    volumes:
      - ./config:/app/config:ro
      - ./data:/app/data
    environment:
      CONFIG_PATH: /app/config/searches.yaml
```

## Useful commands

Show the built search URLs (validates the config without fetching anything):

```bash
docker compose run --rm scanner python -m app.main --show-urls
```

Verify SMTP settings with a test mail:

```bash
docker compose run --rm scanner python -m app.main --test-mail
```

Search once and just log matches instead of mailing them:

```bash
docker compose run --rm scanner python -m app.main --once --dry-run
```

Forget the stored listings for one search (`all` for every search):

```bash
docker compose run --rm scanner python -m app.main --reset "Mountain Bike"
```

Run the tests:

```bash
docker compose run --rm scanner python -m pytest
```

## Configuration reference (per search)

| Field | Default | Meaning |
|---|---|---|
| `name` | – | unique name, shown in the mail subject |
| `query` / `queries` | – | one search term or several terms for the same search |
| `url` / `urls` | – | ready-made Kleinanzeigen search URLs instead of search terms |
| `category_id` | – | category from the URL (`k0c161`), usable even without a search term |
| `enabled` | `true` | temporarily disable a search |
| `interval_minutes` | `15` | time between two runs (min. 5) |
| `recipients` | global | recipients for this search only |
| `price_min` / `price_max` | – | price range in euros |
| `price_filter_in_url` | `true` | also apply the price range as a URL filter |
| `negotiable` | `any` | `any` / `only` (negotiable only) / `exclude` (fixed price only) |
| `include_without_price` | `false` | report listings with no price despite a price range |
| `include_free` | `true` | always include "free to a good home" listings |
| `location_id` / `radius_km` | – | radius search |
| `only_offers` | `true` | hide "wanted" ads |
| `exclude_sponsored` | `true` | hide sponsored PRO/dealer listings |
| `keywords.all_of` | `[]` | every term must be present |
| `keywords.any_of` | `[]` | at least one term must be present |
| `keywords.none_of` | `[]` | none of these terms may be present |
| `fetch_details` | `false` | also load the listing page (see Notes) |
| `max_pages` | `1` | result pages per search term (~25 listings per page) |
| `max_new_per_run` | `25` | upper limit of matches per mail |
| `seed_on_first_run` | `true` | first run sends no mail |
| `notify_on_price_drop` | `false` | report a known listing again if the price drops |

## Structure

```
app/
  main.py       CLI + endless loop with scheduler and signal handling
  runner.py     one search run: fetch, filter, store, mail
  scraper.py    URL building and HTML parsing
  fetcher.py    HTTP client with throttling, retry and block detection
  filters.py    price, negotiable-price and keyword logic
  storage.py    SQLite (seen listings, run state)
  notifier.py   SMTP sending, HTML and text mail
  config.py     load and validate YAML from CONFIG_YAML or a file
config/searches.example.yaml
tests/          unit tests, including a fixture of a real result page
```

## Notes

- The search results list already contains the full listing text, so keyword filters work
  without an extra request. `fetch_details: true` additionally loads the listing page –
  only needed if Kleinanzeigen ever truncates the text in the list.
- The interval is deliberately limited to a minimum of 5 minutes, with a 3–4.5 second pause
  between individual requests. On HTTP 403/429 the scanner pauses the affected search until
  the next interval and logs it.
- Multiple `queries` mean multiple requests per run (one request per term and page).
- If Kleinanzeigen changes its HTML, the extractors in `app/scraper.py` are the only place
  that needs updating; `tests/fixtures/srp_sample.html` contains a real result page as a
  reference, `tests/test_scraper.py` checks old and current markup.
