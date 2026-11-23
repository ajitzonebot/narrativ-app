# Narrativ

An Android app and data pipeline for Indian stocks (NSE and BSE main board). The pipeline reads exchange prices, XBRL
filings, shareholding and announcements every trading day, scores every stock, and checks every number against its
source. The app shows the result.

## Install the app

Download the latest APK from [Releases](https://github.com/ajitzonebot/narrativ-app/releases/latest). The app checks
`version.json` here and offers updates by itself. The app needs an access key, so it shows data only to its owner.

## What's in this repo

| Folder | What |
|---|---|
| `narrativ/`, `run.py`, `scripts/` | The pipeline (Python): prices, filings, shareholding, announcements, scores, checks |
| `tests/` | Tests (`pytest`); HTTP is replayed from `tests/cassettes/` |
| `worker/` | Cloudflare Worker that serves the data to the app |
| `android/` | The Android app (Kotlin, Jetpack Compose) |
| `docs/` | The web version of the app |
| `data/`, `docs/data/` | Data taken straight from exchanges and filings: financials, fundamentals, shareholding, classification, price charts |
| `reference-workflows/` | The GitHub Actions workflows that run the pipeline, for reference (they don't run here) |

Everything here is copied every evening from a private repo. The Buy rules, research notes, verdicts and picks stay
private.

## Run the pipeline yourself

1. Python 3.11+: `pip install -r requirements.txt`
2. `python run.py` runs the daily pipeline into `docs/data/`.
3. `pytest` runs the tests.

The workflows in `reference-workflows/` show the full schedule and the secrets each step needs (Cloudflare, Gemini).

## Licence

[MIT](LICENSE)
