# Xalient

**A local-first hiring-signal radar for X.**

Xalient watches X/Twitter search results for early hiring signals, filters the
noise with a local Ollama model, and drafts outreach you can review before doing
anything with it. It is intentionally small, self-hosted, and manual-first: no
paid APIs, no secret API keys, no automated sending.

It is built for the moment when a founder posts "we're hiring our first data
engineer" and you want to see it while it is still fresh.

## What It Does

- Monitors configurable X search queries in a continuous polling loop.
- Uses a persistent Playwright browser profile so you can log into X manually.
- Stores discovered posts in SQLite and deduplicates by tweet URL.
- Sends each new post to a local Ollama model for hiring relevance scoring.
- Drafts a short public reply and a longer DM-style message.
- Shows everything in a dark, live-refreshing dashboard for manual review.
- Lets you approve or skip drafts without ever auto-sending anything.

## Why Local-First

Xalient is designed around a simple constraint: useful automation should not mean
handing a pipeline of career context, targets, and outreach drafts to paid APIs.

The scraper runs locally. The database is local. The LLM runs locally through
Ollama. The dashboard is a plain HTML file served by FastAPI. The only external
site involved is X itself, accessed through a normal visible browser session that
you control.

## Stack

- Python 3.11+
- FastAPI
- Playwright with a persistent Chromium profile
- Ollama, default model `llama3.2`
- SQLite via the standard `sqlite3` module
- Vanilla HTML/CSS/JS
- `.env` configuration

No ORM. No React. No build step. No paid APIs.

## Project Layout

```text
.
├── agent.py          # Ollama classification and outreach drafting
├── api.py            # FastAPI app, dashboard routes, background scraper task
├── dashboard.html    # Single-file live review dashboard
├── database.py       # SQLite schema and small data helpers
├── scraper.py        # Playwright polling loop for X search results
├── requirements.txt  # Pinned Python dependencies
└── .env.example      # Configuration template
```

## Quickstart

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Install and start Ollama:

```bash
ollama pull llama3.2
ollama serve
```

Create your local config:

```bash
cp .env.example .env
```

Run Xalient:

```bash
uvicorn api:app --reload
```

Open the dashboard:

```text
http://127.0.0.1:8000
```

On first run, Playwright opens a visible Chromium window. Log into X manually in
that browser. The session is saved in `./chrome_profile`, so future runs should
reuse the same login unless X expires it.

## Configuration

Edit `.env` to tune the system:

```env
CHROME_PROFILE_PATH=./chrome_profile
PORTFOLIO_URL=https://annesha.dev
SEARCH_QUERIES=hiring data engineer,hiring AI engineer,founding engineer,looking for ML engineer,join our team early stage
POLL_INTERVAL_MINUTES=3
MIN_FOLLOWER_COUNT=500
OLLAMA_MODEL=llama3.2
OLLAMA_URL=http://localhost:11434
```

The default drafting context is currently tailored for Annesha: AI and big data
engineering, early-stage startups, Python, Spark, Kafka, FastAPI, RAG systems,
neuro-symbolic AI, and cloud infrastructure. Update `agent.py` if you want the
drafts to represent a different person or portfolio.

## Dashboard

The dashboard refreshes every 30 seconds and shows:

- Live stats for scraped posts and draft statuses.
- Pending hiring-signal cards, newest first.
- Original tweet text and author metadata.
- Editable reply and DM drafts.
- Approve and Skip actions.
- A brief visual highlight when new cards arrive.

Approved drafts are only marked as approved. Xalient never sends messages,
posts replies, or opens a compose box on your behalf.

## API

- `GET /drafts` returns pending drafts joined with post data.
- `POST /drafts/{id}/approve` marks a draft approved.
- `POST /drafts/{id}/skip` marks a draft skipped.
- `GET /stats` returns total posts, pending drafts, approved, skipped, and last
  poll time.

Approve and skip endpoints accept optional edits:

```json
{
  "reply_draft": "Edited reply",
  "dm_draft": "Edited DM"
}
```

## Reliability Notes

Xalient is intentionally defensive:

- Duplicate tweets are skipped by unique `tweet_url`.
- Selector and network errors are logged without crashing the polling loop.
- Ollama timeouts or malformed responses skip the current post and continue.
- Processed posts are marked even when classification fails, avoiding infinite
  retries on bad inputs.

## Known Limitations

X does not provide a stable free public API for this use case, so Xalient relies
on web UI selectors. Those selectors can break when X changes its frontend.

The selector-sensitive code lives in:

- `scraper.py`, especially `_extract_tweets_from_page()`
- `scraper.py`, especially `_extract_follower_count()`

Follower counts are also not reliably present in search result cards. Xalient
visits the author's profile for new candidate tweets to enforce
`MIN_FOLLOWER_COUNT`. If the count cannot be read, it logs the issue and treats
the account as meeting the threshold so the loop can keep moving.

## Roadmap Ideas

- Source plugins for other public communities.
- Per-query confidence thresholds.
- Better dashboard filters and search.
- Export approved drafts as CSV or Markdown.
- Prompt profiles for different people or target roles.
- Safer selector diagnostics when X changes markup.

## Ethos

Xalient is not a spam machine. It is a small signal tool for spotting relevant
opportunities, drafting thoughtful outreach, and keeping the human in charge.
