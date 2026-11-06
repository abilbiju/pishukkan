# Pishukkan

Pishukkan is a personal finance ledger with a responsive dashboard and an optional Telegram bot. It uses exact decimal amounts, keeps user records partitioned by account identity, excludes transfers from income/expense totals, supports CSV export, budgets, and conservative transaction parsing. It runs locally with SQLite and can use Supabase PostgreSQL via `DATABASE_URL`.

## Run locally

Requires Python 3.11+ (the Docker image uses 3.12).

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set DASHBOARD_API_TOKEN to a long random secret.
uvicorn app.main:app --reload
```

Open http://localhost:8000 and enter `DASHBOARD_API_TOKEN` from `.env`. The dashboard does not contain production sample records; it starts empty. Run the accounting tests with `pytest`.

## Telegram

Create a bot with BotFather, set `TELEGRAM_BOT_TOKEN`, then run `python -m app.bot`. Each Telegram account receives its own `telegram:<id>` ledger. Supported text entries require an explicit amount (for example, “Spent 250 on dinner” or “Received 15000 salary”). Receipt photos use local OCR; if `GROQ_API_KEY` is configured, the image is also sent to Groq Vision for structured field extraction. Scans are presented for confirmation; if the total and date are clear, tap **Confirm & save**. If either is unclear, enter them with `/receipt_save AMOUNT YYYY-MM-DD`. Common report commands include `/balance`, `/expense_today`, `/expense_week`, `/expense_month`, `/income_month`, `/savings`, `/categories`, `/recent`, `/transactions`, and `/undo`. `/expense_july` uses the current year. The dashboard supports any chosen month.

The web dashboard API uses a single private bearer token, suitable only for a private, single-owner deployment behind TLS. Do not expose it or use the static token model for a multi-user/public product. Telegram records and dashboard records currently use separate identities; connect a Telegram identity to the dashboard only after implementing an explicit account-link flow. Text parsing is deliberately conservative and does not call an LLM to invent figures. When `GROQ_API_KEY` or `GEMINI_API_KEY` is configured, unmatched text questions are answered from the current user's read-only ledger context. Set `LLM_PROVIDER=groq`, `LLM_PROVIDER=gemini`, or leave it as `auto` to prefer Groq and fall back to Gemini. The assistant cannot create or edit transactions; explicit transaction messages continue through the local parser.

## Database and deployment

Set `DATABASE_URL` to a Supabase PostgreSQL connection string (use its pooler URL if required by your network). Apply `migrations/001_initial.sql` in Supabase SQL editor, or let the API create tables at startup. Keep Supabase credentials server-side; never place service role keys in browser code. The migration enables RLS as a safe default; this app accesses PostgreSQL only from the server and uses its own user scoping.

For an Oracle Cloud Ubuntu ARM64 VM install Docker Engine and Compose, copy the project and `.env`, set secrets, then:

```sh
chmod +x scripts/deploy-oracle.sh
./scripts/deploy-oracle.sh
```

The Dockerfile uses a multi-architecture Python base and works on Ampere ARM64. Put the API behind a TLS reverse proxy and restrict inbound ports. For Vercel, deploy the `web` directory as a static site and configure the API origin/reverse proxy; the current frontend calls `/api` on its serving origin, so same-origin routing or a proxy rewrite is required. A future split-origin deployment should add a build-time API base URL and a proper login flow.

### Render

`render.yaml` defines a Docker web service and a Telegram background worker. Create a
free PostgreSQL database outside Render (for example Supabase), then create a Blueprint
from this repository in Render and provide the same PostgreSQL `DATABASE_URL`, Telegram
token, and LLM keys when prompted. Do not use the default SQLite URL on Render: free
containers have ephemeral filesystems, and the web and worker must share PostgreSQL.
Render background workers may require a paid plan depending on the current Render
offering; if so, deploy only the web service on Render and keep the Telegram worker on
an always-on free VM until webhook support is added. Receipt files currently use
temporary container storage on Render and should not be treated as durable backups.

## Environment

See `.env.example`. Required secrets for a private deployment are `DASHBOARD_API_TOKEN` and `APP_SECRET`; set `DATABASE_URL` to persistent PostgreSQL before production. `TELEGRAM_BOT_TOKEN` is needed only for the bot. `GROQ_API_KEY` is optional; when set, Telegram receipt images are sent to Groq's vision model and can answer natural-language questions. `GEMINI_API_KEY` enables Gemini question answering. `LLM_PROVIDER` accepts `auto`, `groq`, or `gemini`; `GROQ_MODEL` defaults to `qwen/qwen3.8-27b` and `GEMINI_MODEL` to `gemini-2.0-flash`. `OPENAI_API_KEY` is not used by the current application.

## Current feature boundaries

Financial records, totals, category breakdowns, recent entries, soft deletion, budget setup, CSV export, and a database-backed monthly summary endpoint are implemented. Telegram receipt photos are stored privately, OCR-scanned, and saved only after confirmation; identical receipt files already attached to a transaction are rejected. Do not expose the receipt directory as static web content. XLSX/PDF exports, general duplicate matching, voice transcription, scheduled notifications, full transaction editing, OAuth/multi-user authentication, and production backup encryption/rotation are not yet implemented. Receipt OCR needs Tesseract installed in the OS and PyMuPDF/Pillow/pytesseract installed in Python; the Docker image includes Tesseract.
