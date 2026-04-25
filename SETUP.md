# Mosaic — Setup Guide

End-to-end instructions for running Mosaic locally. Two paths: **Docker** (recommended) and **bare metal**. Both end at a working frontend + API + Celery worker generating real theses from SEC filings.

---

## 1. Prerequisites

| Tool | Version | Notes |
| ---- | ------- | ----- |
| Python | 3.11+ | bare-metal path only |
| Node.js | 20+ | bare-metal path only |
| Docker Desktop | latest | Docker path; provides Postgres + Redis even for bare-metal |
| Git | any | for cloning |

You will need a couple of API keys (Anthropic, OpenAI). EDGAR is free.

---

## 2. API keys — where to get them

### Groq (REQUIRED)
- URL: https://console.groq.com → API Keys → Create API Key.
- Pricing: free tier with generous rate limits (and a paid tier if you exceed them).
- Default model: `llama-3.3-70b-versatile` (128k context window — fits full SEC filings).
- Set in `.env`:
  ```
  GROQ_API_KEY=gsk_...
  GROQ_MODEL=llama-3.3-70b-versatile
  ```

### OpenAI (REQUIRED — embeddings only)
- URL: https://platform.openai.com → API Keys → Create new secret key.
- Pricing: `text-embedding-3-large` is $0.13/M tokens. MVP costs **< $1**.
- Set in `.env`: `OPENAI_API_KEY=sk-...`

### SEC EDGAR (NO KEY)
- Free, public REST API. No auth, but EDGAR ToS requires a User-Agent identifying you.
- Set in `.env`: `EDGAR_USER_AGENT=Your Name your-email@example.com`
- Without a contact email there, EDGAR will throttle/block you.

### (Optional) Supabase as managed Postgres
- URL: https://supabase.com → New Project.
- Settings → Database → Connection string → use the `postgresql://` URI and rewrite to `postgresql+asyncpg://...` for `DATABASE_URL`.
- SQL Editor: run `CREATE EXTENSION IF NOT EXISTS vector;` once.
- Skip the local `postgres` Docker service if you go this route.

---

## 3. Setup — Docker (recommended)

```bash
# 1. Clone (or download) the repo
git clone <your-repo>
cd mosaic

# 2. Create your environment file
cp .env.example .env
# Edit .env: set ANTHROPIC_API_KEY, OPENAI_API_KEY, EDGAR_USER_AGENT

# 3. Build and start everything (postgres, redis, backend, worker, frontend)
docker-compose up --build
# (leave this running — first run pulls images and builds, which takes a few minutes)

# 4. In a second terminal, run the initial migration:
docker-compose exec backend alembic upgrade head

# 5. Seed the universe (20 semiconductor companies):
docker-compose exec backend python /scripts/seed_companies.py

# 6. Run the end-to-end demo (fetches NVDA 10-Ks, runs the agent pipeline,
#    prints any generated theses to stdout):
docker-compose exec backend python /scripts/demo_run.py
```

Open:
- Frontend → http://localhost:3000
- API docs → http://localhost:8000/docs
- Health   → http://localhost:8000/health

---

## 4. Setup — bare metal (no Docker for the app)

You still need Postgres + Redis somewhere. The fastest way: run those two as Docker containers and skip the rest.

```bash
# 1. Clone
git clone <your-repo>
cd mosaic

# 2. Postgres + Redis via Docker (skip if you have them locally)
docker run -d --name mosaic-pg \
  -e POSTGRES_DB=mosaic -e POSTGRES_USER=mosaic \
  -e POSTGRES_PASSWORD=devpassword \
  -p 5432:5432 pgvector/pgvector:pg16

docker run -d --name mosaic-redis -p 6379:6379 redis:7-alpine

# 3. Backend Python env
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 4. .env at the repo root
cd ..
cp .env.example .env
# Edit .env. For bare metal, set:
#   DATABASE_URL=postgresql+asyncpg://mosaic:devpassword@localhost:5432/mosaic
#   REDIS_URL=redis://localhost:6379/0

# 5. Migrations and seed
cd backend
alembic upgrade head
cd ..
python scripts/seed_companies.py

# 6. Run the API
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 7. In a new terminal: Celery worker
cd backend
source .venv/bin/activate
celery -A app.tasks.celery_app worker --loglevel=info -Q filings,theses

# 8. In another terminal: frontend
cd frontend
npm install
npm run dev

# 9. Demo
cd ..
python scripts/demo_run.py
```

---

## 5. Verification checklist

After setup, all of these should pass:

- [ ] `curl http://localhost:8000/health` returns `{"status":"ok",...}`.
- [ ] `curl http://localhost:8000/api/companies` returns 20 semiconductor companies.
- [ ] `curl http://localhost:8000/api/theses` returns `{"theses":[],"total":0,...}` before the demo.
- [ ] Frontend loads at http://localhost:3000 with the dashboard layout.
- [ ] Celery worker logs show `ready` and a list of registered tasks (`ingest_company_filings`, `extract_and_analyze`, `analyze_company`).
- [ ] `python scripts/demo_run.py` (or via docker exec) prints at least one thesis with confidence ≥ 0.5 and a non-empty evidence chain.

---

## 6. Tests

```bash
# from backend/ with your venv active
pytest -q
```

The test suite uses an in-memory SQLite database and mocks the Anthropic client, so it does not require any API keys or external services.

---

## 7. Troubleshooting

### `pgvector` extension missing
```sql
-- Connect with `psql` (or Supabase SQL Editor) and run:
CREATE EXTENSION IF NOT EXISTS vector;
```

### EDGAR returning 403 / rate-limit errors
- Ensure `EDGAR_USER_AGENT` contains a real email and identifies you. EDGAR blocks unidentified clients.
- The client already throttles at 10 req/sec. If you've been blocked previously, wait a few minutes.

### Groq API errors
- Verify the key at https://console.groq.com/keys.
- Default model is `llama-3.3-70b-versatile`. Faster alternatives: `llama-3.1-8b-instant`, `llama-3.1-70b-versatile`. Override via `GROQ_MODEL` in `.env`.
- 429 rate-limit errors usually mean you've hit the free-tier per-minute cap; the agent retries with exponential backoff, but heavy parallel runs may exhaust it. Reduce concurrency or upgrade your Groq tier.

### Celery: `KeyError: 'visibility_timeout'` or worker exits immediately
- Confirm `REDIS_URL` is reachable. Inside Docker it must be `redis://redis:6379/0`. Bare metal: `redis://localhost:6379/0`.

### Alembic: cannot find `vector` type
- pgvector extension wasn't installed before the migration. Either run `CREATE EXTENSION IF NOT EXISTS vector;` manually, or use the `pgvector/pgvector:pg16` image (the included `docker-compose.yml` does this).

### Migration partially ran
- `alembic downgrade base` then `alembic upgrade head`. If that's blocked by a vector index, drop the `embeddings` table manually first: `DROP TABLE IF EXISTS embeddings CASCADE;`.

### `/api/graph` returns empty even after `demo_run.py`
- The in-memory graph hydrates on backend startup. After running the demo, hit `GET /api/graph?refresh=true` to force a reload from the database.

---

## 8. Where to look in the code

| You want to... | File |
| -------------- | ---- |
| Understand the schema | `backend/app/db/models.py` |
| Tweak an agent prompt | `backend/app/prompts/*.j2` |
| Add a new API endpoint | `backend/app/api/*.py` + register in `router.py` |
| Add a Celery task | `backend/app/tasks/*.py` + register in `celery_app.py` |
| Change the company universe | `data/seed/semiconductor_universe.json` |
| Adjust pipeline thresholds | `backend/app/config.py` (`DELTA_SIGNIFICANCE_THRESHOLD`, `THESIS_MIN_CONFIDENCE`, etc.) |
| Style the UI | `frontend/src/index.css` and `frontend/tailwind.config.js` |
