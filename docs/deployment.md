# Production deployment

TripTab uses HTTPS browser → Vercel Next.js → same-origin `/api/v1/*` rewrite →
Render FastAPI → paid Render PostgreSQL. Frontend root is `frontend/`; backend
root is `backend/`. Accounting, immutable history and authorization stay in FastAPI.
This document describes configuration and verification; a checked-in manifest
alone does not establish that any production resource or backup exists.

## Provider configuration

`render.yaml` specifies Singapore for backend and database, PostgreSQL **17**
(matching local/CI), paid database compute `0.1c-256mb`, 1 GB storage, and paid
backend compute `1c-2g`. Check current price/billing in the selected workspace
before provisioning. These are initial small-deployment sizes, not availability
or capacity guarantees. Storage is durable and the database is not the expiring
Free plan. Monitor storage and increase it before capacity is reached.

Render uses Python 3.11 from `backend/.python-version`, locked production-only
`uv sync`, and the following **one** pre-deploy command:

```sh
uv run --locked --no-dev alembic upgrade head
```

It runs after build and before the new release starts. Paid web services support
this step. Do not also run migrations manually for that release or add them to
startup. Failed releases can retry this idempotent command; there is no guarantee
that a failed provider command is never retried. Serialize backend releases.
Verify deploy logs and revision `20261003_0003` after the first successful release.
There are no new or edited schema revisions in M11.

The service binds Render's `$PORT` on `0.0.0.0`, with one worker, one instance,
no reload, no raw access logs and no proxy-header trust. Its concurrency cap is
eight, preserving M10's limit and accommodating the trip screen's six concurrent
reads. The 2 GB instance reserves memory for the application alongside bounded
Argon2 work; a 512 MB instance cannot safely budget eight simultaneous password hashes.
Over-capacity requests receive Uvicorn's 503; the `/ready` health check exercises
database connectivity. `/health` remains independent liveness. No persistent
backend filesystem is needed.

For Vercel, create/use one TripTab project with Next.js preset, repository root
directory `frontend`, Node **22.x**, install `npm ci`, build `npm run build` and
framework-default output. Set the server-only backend origin before building.
No duplicate frontend or API functions are needed. `next.config.ts` owns rewrites
and headers; `frontend/vercel.json` only disables automatic Git deployments.
The public production alias must be usable without Vercel deployment protection.
Keep previews protected and do not allow preview origins to mutate production.

## Environment checklist

Set these in provider environment/secret storage. Do not copy real values into
Git, tickets, shell command arguments or reports.

| Provider / variable | Purpose / production setting |
| --- | --- |
| Vercel `TRIPTAB_API_ORIGIN` | Exact HTTPS Render service origin; server-only; no path or trailing slash; embedded at build time |
| Render `DATABASE_URL` | Generated private connection string from `triptab-db`; standard `postgresql://` is normalized to the installed psycopg driver without changing credentials or query options |
| Render `PGSSLMODE` | Native libpq setting `require`, requiring TLS without plaintext fallback |
| Render `TRIPTAB_ENV` | `production`; validates configuration before serving |
| Render `TRIPTAB_ALLOWED_ORIGINS` | Exact public HTTPS Vercel/custom origin; no wildcard; deliberately supplied during provisioning |
| Render `TRIPTAB_COOKIE_NAME` | `triptab_session` |
| Render `TRIPTAB_COOKIE_SECURE` | `true` |
| Render `TRIPTAB_SESSION_SECONDS` | `604800` |
| Render `TRIPTAB_LOG_LEVEL` | `INFO`; no DEBUG |
| Render `TRIPTAB_DEBUG` | `false` |
| Render `TRIPTAB_AUTH_RATE_LIMIT` | `10` shared authentication requests per socket IP/window |
| Render `TRIPTAB_AUTH_GLOBAL_LIMIT` | `100` authentication requests per process/window |
| Render `TRIPTAB_AUTH_RATE_WINDOW` | `60` seconds |

Vercel never receives database credentials. No `NEXT_PUBLIC_*` backend origin,
CORS middleware, browser token storage or extra auth secret is required.

## Database access and recovery

Use the internal URL in the same Render workspace and region. `PGSSLMODE=require`
is appropriate for Render's private self-signed certificate; Render does not
support `verify-full` on internal connections. This provides encryption, not
certificate identity verification, and relies on Render's private network.
Generated database credentials stay in Render. The service role owns this app's
database/schema to run migrations; do not use it for unrelated databases.

`ipAllowList: []` disables external database access. Use provider shell/private
connectivity for administration and provider-native exports. If external access
is essential, allow only the operator's current `/32`, require TLS using the full
external hostname, and remove the allowance afterward. Never use `0.0.0.0/0`.

Paid Render PostgreSQL provides continuous point-in-time recovery: currently
three days in Hobby workspaces and seven days in Pro or higher. Verify the actual
workspace tier, paid database status and available Recovery window after creation;
do not infer backup readiness from YAML. After smoke data, trigger a logical export
from Recovery and confirm it completes. Render retains exports for seven days;
download encrypted/restricted off-provider copies if longer retention is needed.
Do not commit archives or signed export URLs. Initial recovery objectives are
bounded by that verified window; longer retention requires an operator schedule.
See [Render recovery](https://render.com/docs/postgresql-backups) and the
[restore and session revocation procedure](operations.md#backup-and-recovery).

## Deployment ordering and CI gate

1. Pass local backend pytest/Ruff/Alembic check, frontend tests/lint/typecheck/build
   and existing Playwright flows against the local production build. Tests never
   point at production. Scan tracked files and Git history for secrets.
2. Commit repository changes, push and verify both GitHub CI jobs for the exact SHA.
   Use that immutable green commit for both provider deployments.
3. Reserve a Vercel project and its production alias without serving a preview as
   the product. Record its exact HTTPS origin, resolving the bootstrap dependency.
4. Provision the paid Render database and backend from the green commit. Supply
   the reserved browser origin in `TRIPTAB_ALLOWED_ORIGINS`. The Render pre-deploy
   step migrates before serving; do not run a second migration step.
5. Confirm backend `/health`, `/ready`, migration head, one-worker/instance settings
   and safe logs. Set Vercel `TRIPTAB_API_ORIGIN` to that backend HTTPS origin.
6. Deploy Vercel production from the same green SHA. Check that the actual public
   alias exactly matches backend allowed Origin; deliberately correct and redeploy
   if the provider assigned a different alias. Never use a wildcard bootstrap.
7. Run the production checks below, inspect recovery/export capability and scan
   the repository again. Record actual URLs, provider IDs, deployed SHAs and evidence
   in the completion report without secrets.

Initial releases are **manual**. Render `autoDeployTrigger: "off"` and Vercel
`git.deploymentEnabled: false` prevent commit-triggered deploys. Disable automatic
Blueprint sync in the Render dashboard too: a Blueprint sync can deploy config
changes independently of the service's Git trigger. There are no deploy hooks or
deployment jobs added to GitHub CI. Select an exact green SHA in provider manual
deployment/API controls, not an unverified latest commit. Do not run concurrent
releases; provider builds do not duplicate the correctness test suites.

## Proxy, cache, cookies and rate limits

The browser always calls the Vercel origin's `/api/v1/*`. Next.js performs an
external rewrite, not a redirect, forwarding to the same API path on Render.
Verify deployed method, JSON body, `Origin`, cookies, `Set-Cookie`, CSRF headers,
status codes and response headers; local behavior alone is insufficient evidence.
The host-only session cookie is set for the browser-visible origin, with Secure,
HttpOnly, SameSite=Lax and Path `/api/v1`. JavaScript receives only the CSRF token.
Mutations require the configured browser Origin plus session-bound `X-CSRF-Token`
(registration/login require Origin before a session exists).

The backend forces `Cache-Control`, `CDN-Cache-Control` and
`Vercel-CDN-Cache-Control` to `no-store` for API responses, including errors.
Next.js applies the same API headers and `x-vercel-enable-rewrite-caching: 0`.
No private route has `s-maxage`, revalidation or rewrite cache opt-in. Vercel
consumes its targeted cache header, so its absence in the browser is expected;
verify the visible `Cache-Control` and CDN cache status repeatedly, using two
accounts and unauthenticated requests to the **same URL** without cache-busting.

Render ingress/Vercel forwarding does not provide a verified end-client address
to this application. Keep `--no-proxy-headers`: per-IP authentication buckets use
the socket peer and may be shared by unrelated users. The global cap also applies.
Do not trust spoofable `X-Forwarded-For`, enable `--forwarded-allow-ips '*'`, add
Redis or horizontally scale. Restarts reset fixed-window counts; rolling releases
can temporarily overlap old/new process buckets. Request IDs are canonical UUIDs,
not trusted identities. Direct Render access still requires authentication,
trip authorization and allowed Origin/CSRF; the backend URL is not a secret.

## Production smoke and monitoring

Use clearly synthetic unique accounts and trips, never personal credentials.
Keep cookie/password/CSRF values in memory, traces/screenshots with sensitive
content disabled, and report only assertions/IDs. Preserve synthetic financial
history; do not delete ledger rows as cleanup.

- Register A through Vercel; inspect cookie flags and host/path. Create a trip,
  confirm its account-linked Owner, add guests, record an Equal/Exact expense,
  check allocations, balances, suggestions, record a payment, correct an expense
  and payment, void a record and inspect retained history/replacement links.
- Register B in a separate session. B's trip list excludes A's trip; copied UUID
  routes, expenses and histories return 404. Repeated A/B/unauthenticated requests
  to `/auth/me`, `/groups`, and A's `/balances` retain identity/status and no-store;
  never accept a CDN HIT/STALE private response.
- Reload A's browser, log out, verify the old cookie is revoked, log in and check
  persisted trip/history. Missing/invalid CSRF and invalid Origin return 403;
  cross-origin preflight exposes no CORS permission. Verify direct Render access
  has the same authorization boundaries.
- Verify liveness/readiness and disabled production API docs. Valid request IDs
  echo through the proxy. Check Render JSON logs contain route templates/status
  and IDs without cookies/passwords/CSRF/URLs/SQL. Use safe validation failures,
  not destructive fault injection. Check a bounded auth rejection/Retry-After
  without changing limits or locking out actual users.
- Confirm actual paid database plan, version, region, external access restrictions,
  Recovery timestamps/window and completed initial logical export.

Observe Render service Events/deploy logs for failed builds/migrations, runtime
Logs for JSON requests, readiness health checks for DB availability, and the
database Metrics/Recovery pages for capacity and recovery. Vercel Deployments
and Observability/External Origins show frontend/rewrite failures. Availability
monitoring is provider-native; no external monitoring SaaS is added.

## Rollback and limitations

Record the previous accepted application releases and their compatible schema.
Redeploy/rollback to those Render/Vercel releases with the correct paired backend
origin; inspect whether the provider rollback invokes pre-deploy commands before
using it. Do **not** automatically downgrade Alembic. M11 has no schema changes;
initial migrations create the existing schema. For future destructive migrations,
restore/PITR into a separate database, validate ledger/history and migration head,
revoke recovered sessions, then deliberately switch traffic. Account for writes
since the recovery point; retain the source until recovery is accepted.

The initial Vercel alias suffices; purchasing a custom domain is deferred. Adding
one requires deliberately updating allowed Origin and repeating cookie/CSRF/cache
checks. Current limitations include one-worker/instance fixed-window auth limiting,
shared proxy-IP buckets, small compute/storage, no HA guarantee, provider backup
retention and targeted rather than strict script CSP. Session cleanup, distributed
limiting, invitations, reset/verification/OAuth, multi-currency, OCR, recurring
expenses, analytics, idempotency, ledger versioning and payment integration remain
deferred. Development-only npm advisories acknowledged in M10 are not resolved
by this deployment; no breaking dependency changes or audit fixes are introduced.

Provider references: [Render Blueprint schema](https://render.com/docs/blueprint-spec),
[release commands](https://render.com/docs/deploys),
[Postgres connectivity](https://render.com/docs/postgresql-creating-connecting),
[Vercel external rewrite cache changes](https://vercel.com/changelog/vercels-cdn-now-respects-cache-control-headers-from-external-origins-by-default),
[cache header priority](https://vercel.com/docs/caching/cache-control-headers), and
[manual Git deployment configuration](https://vercel.com/docs/project-configuration/git-configuration).
