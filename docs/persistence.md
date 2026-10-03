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
initial migration in `backend/migrations/` is the schema authority.

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
