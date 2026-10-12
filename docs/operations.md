# TripTab operations

M10 prepares a single-instance application; it does not deploy one. Local Compose
remains PostgreSQL development infrastructure. Production uses native Vercel and
Render builds; application Dockerfiles are unnecessary. See
[deployment configuration and release checklist](deployment.md).

## Configuration

`app/config.py` is the backend environment boundary, validated before serving.
Configuration is cached per process; restart after changes. It does not load `.env`
implicitly. Supply environment externally, or explicitly use `uv run --env-file`
for development. Never print configuration secrets.

| Variable | Default / requirement |
| --- | --- |
| `TRIPTAB_ENV` | `development`, `test`, or `production`; explicitly set production |
| `DATABASE_URL` | `postgresql+psycopg://...` or provider `postgresql://...`; required for DB operations and production |
| `TRIPTAB_ALLOWED_ORIGINS` | Comma-separated exact browser origins; absent denies mutations; production requires HTTPS |
| `TRIPTAB_COOKIE_NAME` | `triptab_session`; changing it invalidates browser cookies |
| `TRIPTAB_COOKIE_SECURE` | `true`; development/test HTTP can explicitly use `false` |
| `TRIPTAB_SESSION_SECONDS` | `604800`; permitted 300–2592000 seconds; new sessions only |
| `TRIPTAB_LOG_LEVEL` | `INFO`; DEBUG/INFO/WARNING/ERROR; production rejects DEBUG |
| `TRIPTAB_DEBUG` | `false`; production rejects `true` |
| `TRIPTAB_AUTH_RATE_LIMIT` | 10 authentication POSTs per client IP per window |
| `TRIPTAB_AUTH_GLOBAL_LIMIT` | 100 authentication POSTs total per window |
| `TRIPTAB_AUTH_RATE_WINDOW` | 60 seconds; permitted 1–3600 |

Rate counts must be positive and at most 10000. Cookies retain HttpOnly,
SameSite=Lax, host-only scope and `/api/v1` Path. `__Host-` names are rejected because
this path is not `/`. Production requires a database host, user and nonempty
non-example password, rejects known local/CI/example credentials, and rejects
missing, wildcard, malformed, or non-HTTPS browser origins. Production disables
public API documentation. There is no auth bypass setting.

Root `.env.example` contains public local-only credentials. Never reuse them in
production. Use dedicated database roles, generated credentials, least privilege,
and validated PostgreSQL TLS (prefer `sslmode=verify-full` with the correct CA).
Production uses Neon's direct public endpoint with `PGSSLMODE=verify-full`,
`PGSSLROOTCERT=system` and `PGCHANNELBINDING=require`. URI query options take
precedence; remove/replace any generated `sslmode=require`. Test system trust and
the actual connection from Render, retaining certificate/hostname verification.
See [Neon connection guidance](https://neon.com/docs/connect/connect-securely).
Credential files should be mode 0600 and outside Git. Roles/TLS are provisioned
separately; the application does not configure them.

## Production startup and releases

Supply production environment/secrets externally. From `backend/`:

```sh
uv sync --locked --no-dev --python 3.11
uv run --locked --no-dev python -c 'from app.config import get_settings; get_settings(); print("configuration valid")'
uv run --locked --no-dev alembic upgrade head
uv run --locked --no-dev alembic check
uv run --locked --no-dev uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --limit-concurrency 8 --no-access-log --no-proxy-headers
```

Run migrations **once per release**, before the new build serves traffic; stop/drain
existing traffic where necessary. Web startup never migrates. Migrations 0001–0003
remain unchanged; M10 has no schema revision. Test clean/populated upgrades, back up
before changes, and retain the prior build. Returning to an old build requires
schema compatibility. Downgrades can discard credentials, sessions, roles or void
metadata, so they are not routine rollback. Restore to a separate database when
needed, then deliberately switch traffic and account for writes since the backup.

From `frontend/`, set server-only `TRIPTAB_API_ORIGIN` to the private backend
HTTP(S) origin at **both build and startup**:

```sh
npm ci
npm run build
npm run start -- --hostname 127.0.0.1 --port 3000
```

This origin must contain no credentials/path/query and is required in production.
Rewrites are embedded in the build; rebuild when their target changes. The browser
continues to request same-origin `/api/v1`. No secret belongs in `NEXT_PUBLIC_*`.
Production uses neither Next.js dev nor Uvicorn reload. Size memory for Next.js
and concurrent Argon2 work. A shared semaphore bounds password hash/verify/rehash
operations to two per process, preserving Argon2 parameters; the HTTP cap remains
eight for the dashboard's six parallel reads. Verify memory on the actual service.

Use a TLS ingress for `/` and `/api/*`, preferably routing API traffic directly to
FastAPI. Preserve the browser's Origin. CORS stays disabled and CSRF requires both
allowed Origin and the session token. The command above ignores forwarded headers.
For client-IP limiting behind ingress, strip client-supplied forwarding headers
there and enable Uvicorn proxy headers only for explicit trusted IPs using
`--forwarded-allow-ips`, never `*`. If Next.js rewrites proxy production API traffic,
do not blindly trust its forwarded client headers: sanitize at ingress or retain
socket-IP limiting, which shares one bucket across proxied clients. Validate the
chosen topology before release. Configure HSTS at TLS ingress after verifying HTTPS.

## Health, diagnostics and browser headers

`GET /health` reports process liveness without DB access. `/ready` executes
`SELECT 1` and returns 200 or generic 503 without connection details. It does not
replace migration checks. SQLAlchemy uses pre-ping, five pooled connections, no
overflow, five-second pool/connect timeouts, hidden SQL parameters, and existing
application-owned transactions. Pools close at shutdown.
Render Free probes `/health`; use `/ready` on demand to avoid keeping Neon awake.
Neon/Render idle suspension introduces cold starts. Database-backed sessions
survive backend restarts; process-local rate counters reset. Do not automatically
retry financial writes after a timeout.

Request logs are JSON on stderr: timestamp, level, canonical UUID request ID,
method, route template, status, duration and error category. Valid UUID
`X-Request-ID` values are normalized; others are replaced. Every response echoes
it. Unknown paths use `<unmatched>` rather than arbitrary input. Bodies, queries,
cookies, auth headers, passwords/hashes, bearer/CSRF tokens and DB credentials are
excluded. Unexpected failures return generic 500 with request ID and log exception
type plus file basename/function/line frames, excluding exception text, source and
locals. Disable raw Uvicorn access logs as above; ingress logs must omit queries
and sensitive headers too.

Rejected Guest removal adds `group_id`, `member_id`, and
`removal_rejection_reason` to that same request log. Reasons identify an Owner,
linked Member, persisted financial reference, or one of the four known financial
foreign-key constraints that prevented a concurrent deletion. These are internal
categories, never exception text or SQL. Display names and financial details are
not logged. Use the UUIDs to investigate the exact financial identity; same-named
travelers remain distinct.

API responses use no-store, nosniff, no-referrer, frame denial and restrictive API
CSP. Frontend pages use nosniff/no-referrer plus CSP `frame-ancestors 'none'`,
`base-uri 'self'`, `object-src 'none'`, `form-action 'self'`, and legacy frame denial.
This targeted CSP protects embedding/navigation without breaking Next.js inline
hydration; it is **not** a strict script/XSS CSP. Nonce-based dynamic rendering is
deferred. See [Next.js CSP guidance](https://nextjs.org/docs/app/guides/content-security-policy).

## Financial mutation serialization (M17C)

Expense create/correct/void, generic Settlement create/correct/void, and current
suggestion confirmation share one per-Trip Group row `FOR NO KEY UPDATE` lock in
`_financial_transaction(group_id)`. Acquire it before loading effective financial
state or mutating child rows and retain it through commit/rollback. Future
balance-affecting application writes must use that same wrapper. Repository
helpers flush without committing; direct operational financial writes would bypass
this contract and are unsupported.

Use the PostgreSQL default READ COMMITTED isolation: once a waiting writer obtains
the lock, subsequent effective-history queries see prior commits. Do not change
transaction isolation without revisiting revalidation behavior. NO KEY UPDATE
serializes financial writers but permits FK key-share acquisition by the existing
member/invitation transactions, preserving their member-first lock order.

The dedicated `POST /api/v1/groups/{group_id}/settlement-suggestions/confirm`
returns 409 without writing when the exact tuple is no longer current. Generic
`POST .../settlements` intentionally permits arbitrary actual transfers, including
partial and overpayments; it does not validate a suggestion. See [accounting/API
contracts](accounting.md#confirming-a-current-suggestion-m17c).

M17C adds no schema revision; head remains `20261011_0005`. No production operation
is part of its implementation. After review/push/green CI, a separately approved
release must deploy the backend confirmation command before the new frontend uses
it. No M17C migration is required. PostgreSQL 18 tests exercise simultaneous
confirmation, all six other mutations in both acquisition orders, and FK lock
compatibility. The existing timeout/uncertain-write guidance still applies.

## Authentication limits and retention

Login, registration and password change share a locked, process-local fixed-window
counter, per IP and globally. Rejections return 429 and `Retry-After` before
password work. The global cap bounds tracked IP memory. Window boundaries allow a double burst;
restarts reset counts. This supports the initial **one-worker, single-instance**
deployment, not horizontal scaling. Shared limiting belongs to later scaling;
no Redis or account lockouts are added. Ordinary financial APIs are unaffected.
M9 Argon2id, generic failures, hashed sessions, expiry/revocation/logout and group
authorization remain intact. Financial history is never operationally purged.
Expired/revoked session cleanup remains deferred.

## Backup and recovery

Use PostgreSQL 18 native tools for both the Neon production server and local
Compose cluster. Local `psql`, `pg_dump` and `pg_restore` run inside the
`postgres:18-alpine` Compose container; host PostgreSQL packages are not required.
The preserved historical volumes are described in [persistence](persistence.md#triptab-local-naming-and-preserved-legacy-data). `pg_dump -Fc`
creates a consistent logical archive while PostgreSQL runs. Never copy live Docker
volume files as a backup. Archives contain account hashes, session material and
private financial data: encrypt them, restrict access, store off-host, and define
frequency/retention for acceptable data loss. Use protected PostgreSQL service and
password files or runtime secrets rather than command-line credential URLs.

```sh
umask 077
PGSERVICE=triptab pg_dump -Fc --file=/secure/backups/triptab.dump
PGSERVICE=triptab_admin createdb --owner=triptab triptab_restore_test
PGSERVICE=triptab_admin pg_restore --exit-on-error --no-owner --no-acl --role=triptab --dbname=triptab_restore_test /secure/backups/triptab.dump
```

`PGSERVICE` refers to protected operator service configuration. Restore to an empty
**separate** database with a suitable owner; never use `--clean` on the live DB.
Point verification `DATABASE_URL` at the restored DB, inspect its Alembic revision,
upgrade if needed and run `alembic check`. Compare users, memberships, financial
rows, void/replacement links and balances against expected backup data; check
health/readiness. Retain the source until accepted and remove only the disposable
verification DB. Do not run tests blindly on a real restored DB; fixtures intentionally
require `*_test`. See [pg_dump](https://www.postgresql.org/docs/18/app-pgdump.html)
and [pg_restore](https://www.postgresql.org/docs/18/app-pgrestore.html).

For Neon use a **direct** endpoint and certificate-verifying TLS for both tools.
Create the empty destination through Neon database controls or native `createdb`
with an authorized role; Neon's dump/restore workflow does not support `--create`
or `pg_dumpall`. The local synthetic drill below deliberately retains its
localhost-only safety guard. It must never be redirected to production. Verify
Neon's live Free restore window/quotas at provisioning; short instant restore is
complementary to operator-managed daily and pre-release encrypted off-provider
exports. No paid backup storage/scheduler is implied.

Before routing real traffic to a recovered database, revoke restored login sessions
so an older backup cannot resurrect a previously logged-out session. Require users
to log in again. This changes auth revocation metadata only, never financial history.
The synthetic drill verifies exact session preservation using an already-revoked session.

For a real **local** development backup, use the active container's version-matched
clients from the repository root. Store the archive outside Git:

```sh
umask 077
backup_dir="$HOME/.config/triptab/backups"
mkdir -p "$backup_dir"
chmod 700 "$backup_dir"
backup_file="$backup_dir/triptab-$(date +%Y%m%d-%H%M%S).dump"
docker compose exec -T db pg_dump -U triptab -Fc triptab > "$backup_file"
chmod 600 "$backup_file"
```

Restore only into a newly created **separate local** database, never the live one:

```sh
docker compose exec -T db createdb -U triptab triptab_restore_test
docker compose exec -T db pg_restore -U triptab --exit-on-error --no-owner --no-acl --dbname=triptab_restore_test < "$backup_file"
```

Use protected service/password files and PostgreSQL 18 client containers for
remote operator tooling; never place a credential URL in command arguments.
The commands above use local Unix-socket authentication inside Compose and do not
print a password. A pre-switch complete-cluster `pg_dumpall` SQL archive has a
different format from this custom archive; restore it with `psql` only into an
isolated local recovery cluster after reviewing roles/database-name conflicts.
Do not feed plain SQL to `pg_restore` or restore historical sessions into production.

Repeat the synthetic **local Compose** drill from `backend/`:

```sh
uv run --env-file ../.env python scripts/restore_drill.py
```

It creates two disposable databases, upgrades a clean DB, creates owner/guests,
corrected expenses/payments and void history, dumps/restores with the container's
tools, checks every persisted row and derived balances, then removes both DBs.
The archive stays in memory; no real user data or artifact is retained. This
validates mechanics, not a configured production backup schedule or recovery SLA.

## Pre-deployment gate (Milestone 11)

- Provision PostgreSQL, dedicated roles, validated TLS and generated credentials.
- Configure encrypted off-host backups, retention and an acceptable recovery point.
- Supply production mode, secrets, exact HTTPS origins and Secure cookies.
- Configure TLS ingress, forwarded-header trust and client-IP rate-limit behavior.
- Pass CI, configuration checks, production builds and browser flows.
- After CI is green, run the single operator migration step from that exact
  commit and verify head/check, then manually deploy Render. Free has no pre-deploy
  command. Keep Git auto-deployment and Blueprint auto-sync disabled.
- Verify HTTPS authentication, cookie/CSRF behavior and browser security headers.
- Verify health/readiness, safe request logs and resource/concurrency settings.
- Validate a restore and compare history; document who performs recovery.

Application containers, distributed limiting, cleanup workers, monitoring
SaaS, strict-script CSP, reset/verification/OAuth, idempotency, ledger
versions and multi-currency remain deferred. Reassess dependency advisories at
deployment; a vulnerability scan is not a security guarantee.

## Milestone 12 release boundary

[Trip invitations](invitations.md) add migration `20261011_0004`; deployed revisions
0001–0003 remain unchanged. M12 development/verification uses local Compose only.
Do not run the new revision on Neon or change Render/Vercel until review, push,
green CI and explicit production migration approval. The existing manual migration
before deployment sequence and all production security/configuration remain.
