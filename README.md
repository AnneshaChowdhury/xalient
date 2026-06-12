# Xalient

Xalient is a self-hosted tool for finding hiring posts on X, filtering them with a
local Ollama model, and drafting human-reviewed outreach. It uses no paid APIs and
does not auto-send messages.

## Prerequisites

- Python 3.11+
- Node.js, used by Playwright browser installation
- Ollama installed locally
- The local model pulled:

```bash
ollama pull llama3.2
```

- Ollama running:

```bash
ollama serve
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Review `.env` and adjust search queries, polling interval, follower threshold, or
profile paths as needed.

## First-Run X Login

Run the app:

```bash
uvicorn api:app --reload
```

The scraper opens a visible Chromium window using the persistent profile directory
configured by `CHROME_PROFILE_PATH` (`./chrome_profile` by default). On first run,
log into X manually in that browser. Cookies and session state persist in the
profile directory, so later runs should not require another login unless X expires
the session.

Open the dashboard at:

```text
http://127.0.0.1:8000
```

## How It Works

- `scraper.py` continuously polls X search URLs for configured queries.
- New tweets are inserted into `xreach.db` and deduplicated by `tweet_url`.
- `agent.py` processes unprocessed posts with Ollama and creates pending drafts
  when confidence is above `0.75`.
- `api.py` starts the scraper loop on FastAPI startup and serves dashboard/API
  routes.
- `dashboard.html` refreshes every 30 seconds and lets you approve or skip drafts
  manually.

## API Routes

- `GET /drafts` returns pending drafts joined with post data.
- `POST /drafts/{id}/approve` marks a draft approved.
- `POST /drafts/{id}/skip` marks a draft skipped.
- `GET /stats` returns total posts, pending, approved, skipped, and last poll time.

The approve and skip endpoints accept optional JSON so edits in the dashboard are
saved before the status changes:

```json
{
  "reply_draft": "Edited reply",
  "dm_draft": "Edited DM"
}
```

## Known Limitation

This relies on X's web UI selectors, which may break when X changes its frontend.
The selectors live in `scraper.py`, mainly in `_extract_tweets_from_page()` and
`_extract_follower_count()`.

Follower counts are not always available in search result cards. XReach visits the
author profile for new candidate tweets to enforce `MIN_FOLLOWER_COUNT`; if X does
not expose the count reliably, the scraper logs the issue and treats the count as
the configured threshold so the loop can continue.
