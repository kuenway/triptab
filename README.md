# TripTab

The frontend is a placeholder. The backend exposes `/health` and the first
versioned group, member, expense, and balance APIs. PostgreSQL stores financial
history; the accounting engine derives balances from it.

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
uv run --env-file ../.env alembic upgrade head
uv run --env-file ../.env uvicorn app.main:app --reload --port 8000
```

In another terminal, from the repository root:

```sh
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000 for the placeholder page and
http://localhost:8000/docs for interactive API documentation. The database listens
on `127.0.0.1:5433`; `/health` does not check the database.

## Local API workflow

The product API is under `/api/v1`. For now, it has **no authentication or
authorization**: any caller with access to the local backend can list all groups
and read or create records in any group. This is a development-only behavior, not
a production access policy. Expense records use an internal development recording
user until an authentication milestone supplies real actors. Guest members need
no user account.

With the local setup above running, create a group with
`POST /api/v1/groups` and `{"name":"Weekend"}`. Use its returned `id` to create
Alice and Bob with `POST /api/v1/groups/{group_id}/members` and
`{"display_name":"Alice"}` or `{"display_name":"Bob"}`. Then create an expense:

```json
{
  "description": "Dinner",
  "amount": 900,
  "payer_member_id": "<Alice member UUID>",
  "split_strategy": "equal",
  "participant_member_ids": ["<Alice member UUID>", "<Bob member UUID>"],
  "occurred_at": "2026-10-03T19:00:00+08:00"
}
```

Send that JSON to `POST /api/v1/groups/{group_id}/expenses`, then read stored
allocations at `GET /api/v1/groups/{group_id}/expenses` and derived balances at
`GET /api/v1/groups/{group_id}/balances`. Monetary amounts are whole NTD; the
group currency is always TWD. An Exact expense uses `"split_strategy":"exact"`
and `"splits":[{"member_id":"<UUID>","amount":500}, ...]` instead.

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
npm run build
```

From the repository root, stop PostgreSQL with `docker compose down`. Its named
volume retains local data. Only remove the volume deliberately when the data is
no longer needed.

See [foundation decisions](docs/decisions.md) for the approved domain constraints.
For database migration, transaction, and integration-test commands, see
[persistence documentation](docs/persistence.md).
