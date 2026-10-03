# TripTab

TripTab is a local travel-expense app for trusted groups. The frontend supports
trips, travelers, Equal and Exact expenses, history, derived balances, and suggested
payments. The FastAPI backend stores financial history in PostgreSQL and owns the
accounting.

## Requirements

- Git
- Node.js 22.13 or newer and npm 10 or newer
- Python 3.11 and [uv](https://docs.astral.sh/uv/)
- Docker with Compose, for local PostgreSQL

## Local setup

Terminal 1, from the repository root:

```sh
cp .env.example .env
docker compose up -d db
```

Terminal 2, from the repository root:

```sh
cd backend
uv sync --python 3.11
uv run --env-file ../.env alembic upgrade head
uv run --env-file ../.env uvicorn app.main:app --reload --port 8000
```

Terminal 3, from the repository root:

```sh
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000 for TripTab and http://localhost:8000/docs for API
documentation. The database listens on `127.0.0.1:5433`; `/health` does not check
the database. The frontend calls `/api/v1` on its own origin, which Next.js
rewrites to `http://127.0.0.1:8000` during development. To use another backend,
set `TRIPTAB_API_ORIGIN` in `frontend/.env.local` (see `frontend/.env.example`).

## Local API workflow

The product API is under `/api/v1`. For now, it has **no authentication or
authorization**: any caller with access to the local backend can list all groups
and read or create records in any group. This is a development-only behavior, not
a production access policy. Expense records use an internal development recording
user until an authentication milestone supplies real actors. Guest members need
no user account.

In the browser, create a trip, add travelers, record an Equal or Exact expense,
then read its stored allocations and the group's balances. The payer can be
outside the split. Monetary amounts are whole NTD; currency is always TWD.
The trip's **Suggested payments** section proposes transfers to settle those
balances. These suggestions do not record payments or change financial history.

## Checks

From `backend/`:

```sh
uv run ruff check .
uv run ruff format --check .
uv run --env-file ../.env pytest -q
```

From `frontend/`:

```sh
npm run lint
npm run typecheck
npm test
npm run build
```

From the repository root, stop PostgreSQL with `docker compose down`. Its named
volume retains local data. Only remove the volume deliberately when the data is
no longer needed.

See [foundation decisions](docs/decisions.md) for the approved domain constraints.
For database migration, transaction, and integration-test commands, see
[persistence documentation](docs/persistence.md).
