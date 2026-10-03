# Expense Sharing

Milestone 0 establishes the development environment. The frontend is a placeholder,
the backend exposes only `/health`, and PostgreSQL has no application schema yet.

## Requirements

- Git
- Node.js 22.13 or newer and npm 10 or newer
- Python 3.11 and [uv](https://docs.astral.sh/uv/)
- Docker with Compose, for local PostgreSQL

## Local setup

From the repository root:

```sh
cp .env.example .env
docker compose up -d db
cd backend
uv sync --python 3.11
uv run uvicorn app.main:app --reload --port 8000
```

In another terminal, from the repository root:

```sh
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000 for the placeholder page and
http://localhost:8000/health for the backend health response. The database listens
on `127.0.0.1:5433`. The backend health endpoint does not check the database yet.

## Checks

From `backend/`:

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

From `frontend/`:

```sh
npm run lint
npm run typecheck
npm run build
```

From the repository root, stop PostgreSQL with `docker compose down`. Its named
volume retains local data. Only remove the volume deliberately when the data is
no longer needed.

See [foundation decisions](docs/decisions.md) for the approved domain constraints.
