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
versioned migrations in `backend/migrations/` are the schema authority. M10 retains
these boundaries, adds bounded pre-ping pooling, and documents single-release
migrations and native backup/restore in [operations](operations.md).

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
`TEST_DATABASE_URL` and local authentication settings to an existing `.env`.
Start PostgreSQL and migrate the development database:

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
Authentication and group membership are required. Original recording authors and
owners may void or correct; replacement payments must also satisfy payment
recording permissions. Missing or cross-group targets return 404, an already-voided
target returns 409, and invalid financial values or a blank reason return 422.
Referenced missing or cross-group travelers follow existing creation conventions (404). These additions
retain existing response fields and ordering and add nullable audit metadata and
an explicit active/voided status. No recursive records are embedded.


## Authentication migration (Milestone 9)

Revision `20261003_0003` upgrades the M8 head without changing existing financial
rows, actor IDs, void metadata, or replacement links. It normalizes existing user
emails, adds nullable password hashes, adds owner/member roles and account-linked
ownership constraints, and creates persistent `auth_sessions`. Normalized email
collisions deliberately fail the migration instead of merging historical users.

PostgreSQL enforces normalized unique emails, at most one account-linked owner per
group, and one membership per user per group. Sessions persist only the opaque
bearer token's SHA-256 hash, an independent CSRF token, and lifecycle timestamps.
Authentication uses a short read session that closes before application-owned
financial write transactions. User credentials remain outside financial domain
values. See [authentication and permissions](authentication.md) for cookie, CSRF,
authorization, and local registration details.

Existing user password hashes remain NULL and existing memberships default to
member; no owner or account access is invented. Legacy trips without linked
account access remain private. Reset expendable local data or manually establish
reviewed credentials and membership without changing historical actor IDs.

Upgrade with the same `alembic upgrade head` command above. Downgrade to
`20261003_0002` discards sessions, credentials, and roles while retaining financial
history; perform it only on disposable databases.

## Invitation migration (Milestone 12)

Revision `20261011_0004` follows `20261003_0003`, adding only `trip_invitations`
and its scoped lookup index. Unique token digests, composite trip/member foreign
keys, actor foreign keys and lifecycle checks protect invitation metadata. Existing
`(group_id, user_id)` membership uniqueness is retained. Claiming updates only the
target account association plus invitation metadata in one transaction; no
financial table or historical member ID changes.

Local tests cover populated upgrade preserving old rows/credentials/sessions,
Alembic drift check, disposable downgrade/upgrade, rollback and separate-connection
PostgreSQL races. Downgrade removes invitation audit without unlinking members or
rewriting financial data. Never run it on retained history. Production remains at
M11 until the separately approved release. See [invitations](invitations.md).
