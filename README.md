# TripTab

TripTab is a local travel-expense app for trusted groups. The frontend supports
trips, travelers, Equal and Exact expenses, history, derived balances, and suggested
payments, payment recording, and payment history. The FastAPI backend stores
financial history in PostgreSQL and owns the accounting.

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
user until an authentication milestone supplies real actors. Settlement recording
uses the same internal actor. Both uses must be replaced when authentication is
implemented. Guest members need no user account.

In the browser, create a trip, add travelers, record an Equal or Exact expense,
then read its stored allocations and the group's balances. The payer can be
outside the split. Monetary amounts are whole NTD; currency is always TWD.
The trip's **Suggested payments** section proposes transfers to settle those
balances. Choose **Mark as paid** only after a transfer happened outside TripTab,
check the sender, recipient, amount, and payment time, then choose **Record payment**.
TripTab records the payment; it does not transfer money. The separate **Record
payment** form accepts custom amounts, including partial payments and overpayments.
Recorded payments appear in **Payment history**, and balances and suggestions
refresh from the backend. Suggestions themselves remain unpersisted.

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

## Browser smoke test

One Playwright Chromium test creates a trip, adds travelers and an Equal expense,
records a suggested payment, and checks refreshed balances, suggestions, and
persisted payment history. It uses a separate local `*_e2e_test` database in the
Compose PostgreSQL instance; it refuses the normal development or integration-test
database. The test writes real records, so use this dedicated database only for
browser testing. With Compose running, from the repository root:

```sh
docker compose exec -T db createdb -U splitwise splitwise_e2e_test
cd backend
DATABASE_URL=postgresql+psycopg://splitwise:splitwise_local_only@127.0.0.1:5433/splitwise_e2e_test uv run --locked alembic upgrade head
cd ../frontend
npm ci
npx playwright install chromium
E2E_DATABASE_URL=postgresql+psycopg://splitwise:splitwise_local_only@127.0.0.1:5433/splitwise_e2e_test npm run test:e2e
```

Create the browser-test database only once. Playwright starts isolated backend and
frontend servers on ports 8100 and 3100 and stops them after the test. GitHub CI
provides its own PostgreSQL service, migrates its browser-test database, installs
Chromium, and runs the same smoke test. Server-side idempotency is deferred; UI
submission guards do not guarantee exactly-once payment recording.
