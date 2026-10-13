# TripTab

TripTab is a local travel-expense app for trusted groups. The frontend supports
trips, travelers, Equal and Exact expenses, history, derived balances, and suggested
transfers, settlement confirmation, and immutable payment history. The FastAPI backend stores
financial history in PostgreSQL and owns the accounting.

## Requirements

- Git
- Node.js 22 (22.22.2 or newer within major 22; required by the locked development tooling) and npm 10 or newer; use `nvm use` with the root `.nvmrc`
- Python 3.11 and [uv](https://docs.astral.sh/uv/)
- Docker with Compose, for local PostgreSQL 18 (`postgres:18-alpine`)

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

The product API is under `/api/v1` and requires a real login session and trip
membership. Register at `/register`, or log in at `/login`. Creating a trip also
creates your account-linked Owner traveler; add your companions as guests.
Owners can record guest payments, while registered members have the documented
financial permissions. Financial actors come from the authenticated account.
See [authentication, CSRF, permissions, and legacy-data handling](docs/authentication.md).
For an existing `.env`, add the local cookie and Origin settings from `.env.example`.
Legacy unowned trips are not exposed to newly registered users.

Each traveler row includes its badge and Owner-only invitation/removal actions.
Owners can remove only unused, unclaimed Guests after confirmation. Any financial
history blocks removal, including voided records and zero allocations. Invitation
audit remains stored; linked Member removal is deferred. See [invitation and
removal contracts](docs/invitations.md).

Account settings are available from the Home account menu. Account Name defaults
your name in new Trips only; existing Tripmate names remain unchanged. Password
changes preserve the current session and sign out other sessions. Email changes
and password recovery remain deferred. See [authentication](docs/authentication.md#m19a-account-settings).

Local development uses PostgreSQL 18 with database/user `triptab` and active volume
`triptab_postgres18_data`. Previous data stays in the preserved
`triptab_postgres_data` and `splitwise_postgres_data` volumes; neither is mounted
into the new container. The new volume starts empty and needs Alembic migrations.
See [local naming transition](docs/persistence.md#triptab-local-naming-and-preserved-legacy-data)
before starting Compose if an older container already owns port 5433.

In the browser, create a trip, open **Travelers** to add guests, then return to
**Expenses** to record an Equal or Exact expense. Open **Balances** to view
your net position, traveler balances, and suggested external transfers.
Fresh Equal expenses
select all current travelers and default Paid by to your
linked traveler. You can change the payer or uncheck participants; edits persist
through ordinary form changes. Switching Exact to Equal initializes all travelers,
and saving starts a fresh default form. Corrections retain the original payer and
splits. The payer can be outside the split. Monetary amounts are whole NTD;
currency is always TWD.
The **Suggested transfers** section proposes transfers to settle those balances.
Choose **Mark settled** only after money moved outside TripTab; the confirmation
identifies sender, recipient, and exact amount and states that TripTab does not
transfer money. **Confirm settled** uses a dedicated atomic command that checks
whether this exact suggestion is still current. A stale suggestion returns 409,
refreshes balances/suggestions, and asks you to review rather than retrying.
The normal Balances page has no arbitrary **Record payment** form. The generic
Settlement API still supports partial payments and overpayments; existing payment
editing/voiding remains available in **History**. Suggestions are never persisted.

## Trip navigation

Every Trip shares a compact header and four section links. Desktop uses horizontal
navigation; mobile uses a bottom bar with space reserved below page content.
These are real routes, so direct links, reloads, and browser back/forward retain
the selected section:

| Route | Section |
| --- | --- |
| `/trips/{id}` | Expenses; canonical Trip and invitation-acceptance destination |
| `/trips/{id}/balances` | Personal/traveler net balances and suggested-transfer confirmation |
| `/trips/{id}/travelers` | Travelers and Owner-only invitation/removal management |
| `/trips/{id}/history` | Existing expense/payment history, audit details, and current payment correction/void controls |

Expense edit/void controls stay in Expenses; current payment edit/void controls
are in History, retaining expandable immutable history and version links. History
reuses the existing presentation;
it is not a new activity timeline. Expense entry and editing reuse one form in a responsive dialog: a bottom sheet
on mobile and a centered dialog on desktop. This does not change accounting,
permissions, or API contracts.

## Expense ledger and entry

Expenses shows current records first, grouped by the browser's local calendar day
(Today, Yesterday, or a readable date). Within each group, records sort by occurred
at descending, then recorded at descending, then UUID ascending for stable ties.
Persisted timestamps are unchanged. Details disclose the stored allocations;
participant counts and Your share come from stored split rows, never recomputed
Equal splits. You is resolved by the authenticated account's linked member UUID.
The compact balance summary uses the shared authoritative backend balance data.

Use **+ Expense** to open entry; Edit opens the same form with prefilled values
and a correction reason. New expenses default to the current local date/time,
all Equal participants and the current member as payer; these remain editable.
Closing a changed draft asks for confirmation. Drafts stay in memory only; saving
closes the dialog and refreshes the ledger. Voided versions stay outside the
current ledger, reachable through View edit history or the History section.

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
TRIPTAB_API_ORIGIN=http://127.0.0.1:8000 npm run build
```

Entry loading keeps session resolution (`/auth/me`) separate from the authenticated
trip list (`/groups`). Each unresolved phase reveals its skeleton after 250 ms and
shows “Starting TripTab…” after 5 seconds. Completed requests render immediately;
errors keep their existing Retry actions. Only the brand dot and skeleton bars
pulse, with static feedback when reduced motion is requested.

From the repository root, stop PostgreSQL with `docker compose down`. Its named
volume retains local data. Do not delete the preserved legacy volumes or use
`docker compose down -v` during this transition.

See [foundation decisions](docs/decisions.md) for the approved domain constraints.
For database migration, transaction, and integration-test commands, see
[persistence documentation](docs/persistence.md).

## Browser smoke test

Playwright Chromium flows cover registration, owner and guest travelers,
expenses, current/stale settlement confirmation, editing/deletion UX, persisted audit history,
logout/login, Guest claiming, shared ledgers, isolation between accounts, and
Trip section navigation across reloads, browser history, and mobile/desktop layouts.
They use a separate local `*_e2e_test` database in the
Compose PostgreSQL 18 instance; it refuses the normal development or integration-test
database. The test writes real records, so use this dedicated database only for
browser testing. With Compose running, from the repository root:

```sh
docker compose exec -T db createdb -U triptab triptab_e2e_test
cd backend
DATABASE_URL=postgresql+psycopg://triptab:triptab_local_only@127.0.0.1:5433/triptab_e2e_test uv run --locked alembic upgrade head
cd ../frontend
npm ci
npx playwright install chromium
E2E_DATABASE_URL=postgresql+psycopg://triptab:triptab_local_only@127.0.0.1:5433/triptab_e2e_test npm run test:e2e
```

Create the browser-test database only once. Playwright starts isolated backend and
frontend servers on ports 8100 and 3100 and stops them after the suite. GitHub CI
provides its own PostgreSQL service, migrates its browser-test database, installs
Chromium, and runs the same suite. Server-side idempotency is deferred; UI
submission guards do not guarantee exactly-once payment recording.

To run the same flows against the production frontend, build with
`TRIPTAB_API_ORIGIN=http://127.0.0.1:8100 npm run build`, then add
`E2E_PRODUCTION=true` to the browser-test command. CI uses this production mode.

For production configuration, startup, readiness, request logs, rate limits,
backup/restore and the pre-deployment gate, see [TripTab operations](docs/operations.md).
For the Vercel frontend, Render backend, and paid Render PostgreSQL deployment
configuration and release checklist, see [production deployment](docs/deployment.md).


Use **Edit** on current expenses/payments to save changes; the existing correction
flow saves a replacement and voids the original atomically. The accessible trash
icon opens a **Delete** confirmation, which removes the record's current balance
effect while retaining history. Both require a reason. Current lists show only
active records; expandable history shows previous/voided versions, reasons,
timestamps and replacement links. **View edit history** opens the previous version. See
[accounting policies](docs/accounting.md) and
[correction APIs and migration notes](docs/persistence.md).


Password recovery is available through Sign in → Forgot password. It uses hashed,
30-minute, single-use email tokens and revokes all sessions after reset. Local
email delivery is disabled by default; tests use an in-memory sender. Resend
production setup and deployment are separate approval steps. See
[authentication](docs/authentication.md#password-recovery-m19b) and
[release setup](docs/deployment.md#m19b-password-recovery-release-setup-not-performed-by-implementation).
