# tme-plan-backed

## Installation

Install the required Python packages:

```bash
pip install -r requirements.txt
```

Install Playwright browsers:

```bash
playwright install
```

## Running

```bash
fastapi run api.py
```

## Usage

normally the scraper runs in headless mode
to see what it's doing:

1. Create a .env file
2. set DEBUG=1

## Deployment (Vercel)

The build is driven by `vercel.json` (Python/FastAPI runtime, entrypoint `api.py`, app object `app`).

Required environment variables (set in the Vercel project's Environment Variables settings, not committed):

- `DEBUG` — should be unset or `FALSE` in production.

**Known limitation:** this app scrapes data with Playwright (real Chromium) and caches results to local JSON files under `data/`, refreshed by an in-process background loop. None of that works on Vercel's serverless functions (no Chromium binaries, ephemeral/read-only filesystem, no long-lived background tasks). The app will build and deploy, but the scraping/caching flow needs to be redesigned — e.g. an external scraper/worker writing to an external store (Vercel KV/Blob, a database, etc.) — before it works correctly in production.
