# PostgreSQL persistence

The `backend/app/persistence/` package owns SQLAlchemy models, domain mapping, and
database access. ORM rows are storage shapes. They are converted to the existing
immutable domain values before accounting runs. Neither `app/domain` nor
`app/accounting` imports SQLAlchemy.

`make_engine()` reads `DATABASE_URL` or accepts a URL argument;
`make_session_factory(engine)` creates independent synchronous sessions. The
caller owns `with session.begin():` and therefore commit or rollback. Repository
methods validate group financial context, add rows, and flush, but never commit.
An expense and every split must be saved in the same caller transaction. The
versioned migrations in `backend/migrations/` are the schema authority.

The schema uses UUID keys, `timestamptz` for event and recording times, and
`BIGINT` for integer NTD. Composite foreign keys prevent cross-group payer,
participant, and settlement references. Local check constraints enforce positive
expense/settlement amounts, nonnegative split amounts, TWD with scale 0, and
supported split strategies. The split-total invariant spans rows: the repository
uses the pure accounting validator before the atomic write. A deferred database
constraint trigger can be reconsidered during production hardening; the accounting
algorithm is not duplicated in SQL.

## Local database and migrations

The repository root `.env.example` contains development-only connection values.
Copy it to `.env` if this is a new checkout, or add its `DATABASE_URL` and
`TEST_DATABASE_URL` entries to an existing `.env`. Start PostgreSQL and migrate
the development database:

```sh
cp .env.example .env
docker compose up -d db
cd backend
uv sync --python 3.11
uv run --env-file ../.env alembic upgrade head
```

The Compose service creates the `splitwise` database. Create the separate test
database once from the repository root:

```sh
docker compose exec -T db psql -U splitwise -d postgres -c 'CREATE DATABASE splitwise_test'
```

From `backend/`, run:

```sh
uv run --env-file ../.env pytest -q
uv run --env-file ../.env pytest -m integration -q
uv run pytest -m 'not integration' -q
```

Integration tests require `TEST_DATABASE_URL` to point to a local database whose
name ends in `_test`. They skip clearly when unset and fail clearly when a set
URL cannot connect. The test fixture applies Alembic migrations and wraps each
test in an outer transaction that is rolled back. It never points at the
development database by default. CI starts a dedicated PostgreSQL service,
runs the migration, and executes the full suite.

To check the initial downgrade on a disposable test database, set `DATABASE_URL`
to that test URL and run `uv run alembic downgrade base`, followed by
`uv run alembic upgrade head`. Downgrade removes all application tables and their
data in the selected database; never point it at a database you need to keep.


## Financial audit migration (Milestone 8)

Revision `20261003_0002` upgrades the previous `20261003_0001` head without
rewriting it or changing existing financial values. It adds `expense_voids` and
`settlement_voids`: target UUID as primary key, group UUID, nonblank reason,
`timestamptz` creation time, actor UUID, and optional unique replacement UUID.
Composite target/group and replacement/group foreign keys enforce same-group
links. Actor foreign keys and all financial references use `ON DELETE RESTRICT`;
there are no history-removing cascades. A check prohibits a self-replacement.
The migration also adds `(id, group_id)` uniqueness to settlements for these
composite references; expenses already have it.

A target primary key permits only one void, even with competing requests.
Application checks report an already-voided target as 409. If a stale active check
loses the race, the application catches **only** the two void primary-key
violations after transaction rollback and reports the same conflict. Other
integrity errors retain the existing safe 422 response. General optimistic
locking and idempotency remain deferred.

Repository financial writes and void writes insert and flush; they never commit.
Corrections reuse creation validation inside one application-owned transaction
and commit once. Existing list methods default to full audit history. Their
`effective=True` option uses a `NOT EXISTS` void query for current balances.
Replacement links round-trip on void values rather than altering old Expense or
Settlement financial contracts.

Run `uv run --env-file ../.env alembic upgrade head` and
`uv run --env-file ../.env alembic check` from `backend/` to migrate and detect
schema drift. An existing Milestone 7 database uses the same upgrade command.
On a disposable `*_test` database only, downgrade to `20261003_0001` and upgrade
again for migration sanity. This downgrade drops void metadata and makes stored
originals and replacements all effective; it is **not** a financial undo and
must never be used on history you need to retain.

## Correction API

All paths below start with `/api/v1/groups/{group_id}`:

| POST path | Body | Successful response |
| --- | --- | --- |
| `/expenses/{expense_id}/void` | `{ "reason": "Wrong receipt" }` | 200 original Expense with audit metadata |
| `/expenses/{expense_id}/corrections` | `{ "reason": "Wrong total", "replacement": <complete Expense create body> }` | 201 new Expense with `replaces_id` |
| `/settlements/{settlement_id}/void` | `{ "reason": "Payment did not occur" }` | 200 original Settlement with audit metadata |
| `/settlements/{settlement_id}/corrections` | `{ "reason": "Wrong amount", "replacement": <complete Settlement create body> }` | 201 new Settlement with `replaces_id` |

Expense replacement bodies retain the Equal/Exact discriminator and full creation
fields. Settlement replacement bodies include sender, recipient, positive integer
NTD amount, and aware `occurred_at`. Partial edits and extra fields are rejected.
Missing or cross-group targets return 404, an already-voided target returns 409,
and invalid financial values or a blank reason return 422. Referenced missing or
cross-group travelers follow existing creation conventions (404). These additions
retain existing response fields and ordering and add nullable audit metadata and
an explicit active/voided status. No recursive records are embedded.
