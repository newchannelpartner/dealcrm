# DealCRM

Bespoke CRM for M&A advisory and private credit professionals. Lightweight, AI-powered, installable on iPhone.

## Features

- **Dashboard** — Open todos, active deals, contact counts, recent notes with AI summaries
- **Contacts** — Searchable, tag-filterable table with detail panels and linked deals/notes/todos
- **Deals** — Kanban board by stage (prospect → active → closed/dead)
- **Notes** — Tiptap rich text editor, auto AI analysis on save (Claude extracts summary and action items)
- **PWA** — Install on iPhone home screen for native-app feel
- **Dark theme** — Power-user density, mobile-first responsive
- **HTTP Basic Auth** — Single-user authentication, browser handles credential prompts natively

## Stack

- **Backend**: Python 3.11, FastAPI, SQLAlchemy + SQLite (WAL mode), HTTP Basic Auth
- **Frontend**: Vanilla HTML/CSS/JS, Tiptap editor via CDN
- **AI**: Anthropic Claude (configurable model), direct API calls via `httpx`
- **Scheduler**: APScheduler (wired, ready for daily scan jobs)

## Local Development

### Prerequisites

- Python 3.11+
- pip (or uv)

### Setup

```bash
cd dealcrm

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your values (at minimum set ADMIN_USER and ADMIN_PASSWORD)

# Run
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000 — your browser will prompt for Basic Auth credentials. Use the `ADMIN_USER` / `ADMIN_PASSWORD` you set in `.env`.

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | For AI | — | Claude API key |
| `CLAUDE_MODEL` | No | `claude-haiku-4-5-20251001` | Claude model to use |
| `ADMIN_USER` | Yes | `admin` | HTTP Basic Auth username |
| `ADMIN_PASSWORD` | Yes | random hex | HTTP Basic Auth password |
| `DATABASE_PATH` | No | `/data/crm.db` | SQLite database file path |

## Railway Deploy

The project includes a `Dockerfile` and `railway.toml` pre-configured for Railway:

1. Install [Railway CLI](https://docs.railway.com/develop/cli)
2. `railway login`
3. `railway init` in the project directory
4. Set environment variables in Railway dashboard (or `railway variables set`)
5. `railway up`

The `railway.toml` uses Dockerfile builder, mounts `/data` as a volume (for persistent SQLite), and exposes port 8000.

## iPhone PWA Install

1. Open the app in **Safari** on your iPhone
2. Tap the **Share** button (square with arrow)
3. Scroll down and tap **"Add to Home Screen"**
4. Name it "DealCRM" and tap **Add**

The app launches full-screen with no browser chrome. The bottom nav bar is optimized for thumb reach.

## API Endpoints

All endpoints except `/health` require HTTP Basic Auth. The browser handles credential prompts automatically.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | No | Health check |
| GET | `/contacts` | Basic | List contacts (search, tag filter) |
| GET | `/contacts/{id}` | Basic | Get single contact |
| POST | `/contacts` | Basic | Create contact |
| PUT | `/contacts/{id}` | Basic | Update contact |
| DELETE | `/contacts/{id}` | Basic | Delete contact |
| GET | `/deals` | Basic | List deals (stage filter) |
| GET | `/deals/{id}` | Basic | Get single deal |
| POST | `/deals` | Basic | Create deal |
| PUT | `/deals/{id}` | Basic | Update deal |
| DELETE | `/deals/{id}` | Basic | Delete deal |
| GET | `/notes` | Basic | List notes (entity filter, search) |
| GET | `/notes/{id}` | Basic | Get single note |
| POST | `/notes` | Basic | Create note + trigger AI analysis |
| GET | `/todos` | Basic | List todos (status, priority, entity filter) |
| POST | `/todos` | Basic | Create todo |
| PUT | `/todos/{id}` | Basic | Update todo |
| DELETE | `/todos/{id}` | Basic | Delete todo |
| GET | `/dashboard/stats` | Basic | Aggregate stats + recent notes |

## Project Structure

```
dealcrm/
├── app/
│   ├── main.py           # FastAPI app, scheduler lifecycle
│   ├── models.py         # SQLAlchemy models (Contact, Deal, Note, Todo)
│   ├── database.py       # DB engine, session factory
│   ├── auth.py           # HTTP Basic Auth dependency
│   ├── ai.py             # Claude API integration (analyze_text)
│   ├── routers/
│   │   ├── contacts.py   # CRUD
│   │   ├── deals.py      # CRUD
│   │   ├── notes.py      # CRUD + AI trigger in background thread
│   │   ├── todos.py      # CRUD
│   │   └── dashboard.py  # Aggregate stats
│   └── static/
│       ├── index.html     # Single-page frontend
│       ├── manifest.json  # PWA manifest
│       └── sw.js          # Service worker
├── Dockerfile
├── railway.toml
├── requirements.txt
├── .env.example
└── README.md
```

## FUTURE

### Gmail Email Scan

The `ai.py` module exposes a reusable `analyze_text()` function that Claude uses to extract summaries, takeaways, and todo items from any text. To wire up Gmail scanning:

1. Add a Google Cloud OAuth 2.0 client and Gmail API integration
2. Use the Gmail API's `historyId` cursor for incremental scans
3. Feed email body text through `analyze_text()` to generate contacts and todos
4. Register a daily scan job with the APScheduler (already started in `main.py`)

### Multi-User Auth

All data models include an `owner_id` column (defaults to `1`) as a seam for multi-user support. To enable multi-user:

1. Replace HTTP Basic Auth with JWT or session-based auth
2. Create a `User` model with hashed passwords
3. Filter all queries by `owner_id` (already done via the `get_current_owner` dependency)
4. Add user invitation/management UI

### Daily Scan Scheduler

APScheduler is wired and started in `main.py`'s lifespan handler. The scheduler runs with an empty job registry. To activate daily scans, register a cron job in `_start_scheduler()`:

```python
scheduler.add_job(
    scan_emails,
    trigger='cron',
    hour=7,
    minute=0,
    id='daily_email_scan',
)
```
