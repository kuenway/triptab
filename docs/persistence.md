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

PostgreSQL 18 is canonical for local development, integration/browser tests,
disposable databases and CI. Compose and both CI services use `postgres:18-alpine`.
The application migration head is `20261014_0008`; M19A makes the existing
account display name nullable without changing stored names.

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

The Compose service creates the `triptab` database. Create the separate test
database once from the repository root:

```sh
docker compose exec -T db psql -U triptab -d postgres -c 'CREATE DATABASE triptab_test'
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
target returns 409, and invalid financial values or a blank correction reason
return 422.
Deletion notes are optional; the existing request field remains `reason`.
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
rewriting financial data. Never run it on retained history. The released M12
production baseline uses `20261011_0004`; the M13 revision below remains local
until a separately approved release. See [invitations](invitations.md).

## Guest removal audit migration (Milestone 13)

Revision `20261011_0005` follows `20261011_0004`; deployed migration files are
unchanged. It backfills a non-null `target_member_snapshot_id` from the original
target UUID and makes `target_member_id` a nullable live reference. The existing
composite trip/member foreign key and lookup index remain. New checks require
any live target to match its snapshot and allow a detached target only on a
revoked invitation. A small PostgreSQL trigger makes the UUID snapshot immutable.
The same trigger initializes omitted snapshots on insert so the M12 backend can
still create invitations between the production migration and manual deployment.
No display-name snapshot is needed: retained owner metadata uses UUIDs, while the
traveler UI renders current members and omits removed targets.

Removal locks the Guest, checks Owner authorization, rejects account-linked or
Owner members and every financial reference (including zero allocations and
voided/corrected history), revokes unconsumed invitations, detaches revoked live
references, and deletes the unused Guest in one transaction. Invitation audit
rows remain. Financial foreign keys stay RESTRICT; a competing insert that wins
is translated to 409 after rolling back the entire removal transaction.

Local PostgreSQL 18 tests cover populated upgrade, immutable snapshots, scoped
FKs, lifecycle, atomic failure, removal/acceptance races, and Alembic check.
Disposable downgrade/upgrade to `20261011_0004` is permitted only if no detached
invitation exists. Downgrade deliberately refuses otherwise; it never discards
audit or recreates deleted identities. This migration has not run in production.
After Guest removals create detached audit, retain snapshot-aware application code;
M12 listing responses require a non-null target and cannot read detached rows.

## TripTab local naming and preserved legacy data

Compose uses project name `triptab`, database/user `triptab`, port 5433, and
PostgreSQL 18. Its active volume is `triptab_postgres18_data`, mounted at
`/var/lib/postgresql`; the image initializes `PGDATA=/var/lib/postgresql/18/docker`.
The major-specific directory/mount follows the [official image policy](https://hub.docker.com/_/postgres).
Existing `.env` files are not overwritten: keep POSTGRES_USER, POSTGRES_PASSWORD,
POSTGRES_DB, DATABASE_URL and TEST_DATABASE_URL consistent with `.env.example`.
Integration tests use `triptab_test`, browser tests use `triptab_e2e_test`; all
three are separate databases on the same local server. CI supplies separate
PostgreSQL 18 service instances and never connects to local or production data.

M18A preserves both historical PostgreSQL 17 data volumes:

| Volume | Purpose |
| --- | --- |
| `triptab_postgres18_data` | Active PostgreSQL 18 development/test cluster |
| `triptab_postgres_data` | Preserved previous PostgreSQL 17 TripTab cluster |
| `splitwise_postgres_data` | Preserved legacy PostgreSQL 17 Splitwise cluster |

Never mount either historical volume into the active service or start a newer
major against its data directory. Do not delete these volumes, copy their raw
files into the new volume, or use `docker compose down -v`. The stopped historical
`splitwise-db-1` container may remain; stop it if it still owns port 5433.
`docker compose up -d db` recreates `triptab-db-1` with the new volume without
removing either preserved volume.

Before the local switch, M18A took a complete `pg_dumpall` plain-SQL logical
backup outside Git under `~/.config/triptab/backups/m18a-pg17-*/`, with directory
mode 0700 and file mode 0600. The development database had no application rows;
the browser database contained disposable test fixtures. The new cluster is
fresh-started rather than restoring those fixtures. The backup and old volumes
remain available for separately reviewed logical recovery. Archives include
credential/session material and private history; restrict access and encrypt
before transporting/off-host storage. Never publish backup contents.

Initialize the fresh active development database with the normal commands above,
then create the separate test/browser databases and migrate them. Verify from
`backend/`:

```sh
uv run --env-file ../.env alembic current
uv run --env-file ../.env alembic check
```

Expected revision: `20261014_0008`. Recovery uses native logical dump/restore,
not filesystem copying; see [operations](operations.md#backup-and-recovery).
Both old and new known example passwords remain rejected in production configuration.


## Password reset tokens (M19B)

Revision 20261012_0007 adds password_reset_tokens only, after the deployed 0006.
No User/session/Trip/financial rows are backfilled or changed by upgrade. UUID
identity, restricted User FK, unique SHA-256 hash, UTC timestamps, 30-minute expiry,
used_at and revoked_at record lifecycle without a redundant status. Checks enforce
hash shape, timestamp order and mutually exclusive use/revocation. A trigger
prevents reassignment of ID, User ownership or digest. User_id is indexed for
replacement/invalidation; the unique hash index handles secret lookup.

User-first localized row locks serialize requests, use and failed-delivery
invalidation with login/change-password. Downgrade drops only reset-token rows
and its identity-protection function; it does not reverse successful password or
session changes. Use downgrade only on disposable/reviewed databases. Local tests
verify populated 0006 -> 0007 preservation, fresh migration, check and re-upgrade
on PostgreSQL 18. Production remains at 0006 until a separate approved release.

## Optional deletion notes (M21A)

Revision `20261014_0008` follows `20261012_0007` and makes only the two
financial void `reason` columns nullable. Upgrade leaves every historical row
and meaningful reason unchanged. Existing target/group/actor foreign keys,
unique targets, application-owned immutable financial history and financial
transaction locks remain.
The existing nonblank checks reject empty persisted strings; added checks require
a non-null reason when `replacement_id` identifies a correction.

Expense/Settlement `/void` bodies accept `{}`, `{"reason": null}`, empty or
whitespace-only strings, and meaningful strings. Domain validation normalizes
absent/blank deletion notes to SQL NULL without inventing an explanation.
Meaningful values are preserved verbatim, including historical surrounding spaces.
No existing maximum note length was configured; this milestone does not invent one.
Correction endpoints still require a nonblank string and a complete replacement.

Downgrade to `20261012_0007` is safe only while every void reason is non-null.
It checks both tables before schema changes and refuses otherwise; it never
backfills or rewrites immutable financial audit events. Migration-before-deployment
is compatible with the previous application until note-less voids are created.
After that point pre-M21A code cannot read these events safely. Release requires
explicit review, CI, migration and application deployment approval; M21A is local
only. Frontend optional-note submission requires the M21A backend/schema.
