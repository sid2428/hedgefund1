# Mosaic — AI-Native Cross-Company Investment Thesis Engine

Mosaic is an agent swarm that reads SEC filings (10-K / 10-Q / 8-K), extracts structured facts, builds a company relationship graph, and generates **cross-company investment theses** with full evidence chains. PMs validate or dismiss; the system learns.

## Quick start (Docker)

```bash
cp .env.example .env
# edit .env: set ANTHROPIC_API_KEY, OPENAI_API_KEY, EDGAR_USER_AGENT

docker-compose up --build

# in a second terminal:
docker-compose exec backend alembic upgrade head
docker-compose exec backend python /scripts/seed_companies.py
docker-compose exec backend python /scripts/demo_run.py
```

> Set `GROQ_API_KEY`, `OPENAI_API_KEY`, and `EDGAR_USER_AGENT` in your local `.env` (never commit this file).

Open:
- Frontend: http://localhost:3000
- API docs: http://localhost:8000/docs
- Health:   http://localhost:8000/health

For a step-by-step setup (including manual / no-Docker), troubleshooting, and an API key sourcing guide, see **[SETUP.md](./SETUP.md)**.

## Architecture

```
EDGAR --> Preprocess --> Extractor --> Facts
                                        |
                          +-----+-------+-----+
                          v     v             v
                       Delta  Graph     Embeddings
                          \    /
                           v  v
                        Connector  <-- 2nd-degree graph traversal
                            |
                            v
                         Thesis  -->  FastAPI  -->  React UI
```

## API surface (highlights)

| Method | Path                                | Purpose                       |
| ------ | ----------------------------------- | ----------------------------- |
| GET    | `/api/theses`                       | Paginated thesis feed         |
| GET    | `/api/theses/{id}`                  | Full thesis with evidence     |
| POST   | `/api/theses/{id}/validate`         | Mark thesis validated         |
| POST   | `/api/theses/{id}/dismiss`          | Mark thesis dismissed         |
| GET    | `/api/companies`                    | Tracked companies             |
| GET    | `/api/companies/{ticker}/filings`   | Filing history                |
| POST   | `/api/companies/{ticker}/ingest`    | Trigger pipeline (Celery)     |
| GET    | `/api/graph`                        | Full graph (D3 JSON)          |
| GET    | `/api/graph/{ticker}`               | Ego graph (2-degree)          |
| GET    | `/api/jobs/{job_id}`                | Job status polling            |

## Stack

- **Backend**: Python 3.11, FastAPI, SQLAlchemy 2.0 (async), Alembic, Celery, Redis
- **AI**: Groq Llama 3.3 70B (versatile, 128k context), OpenAI text-embedding-3-large
- **Data**: PostgreSQL 16 + pgvector
- **Graph**: NetworkX (in-memory)
- **Frontend**: React 18, Vite, TailwindCSS, React Query, Zustand, D3

## Repo layout

See the full file tree in `mosaic opus context.pdf` Section 3.
