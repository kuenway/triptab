# Production deployment

TripTab uses HTTPS browser → Vercel Next.js → same-origin `/api/v1/*` rewrite →
Render Free FastAPI → Neon Free PostgreSQL. Frontend root is `frontend/`; backend
root is `backend/`. Accounting, immutable history and authorization stay in FastAPI.
This document describes configuration and verification; a checked-in manifest
alone does not establish that any production resource or backup exists.

## Provider configuration

The approved base cost is **$0/month**: Vercel Hobby, one Render Free web service
in Singapore (512 MB, 0.1 CPU), and one Neon Free project in AWS Singapore
(`aws-ap-southeast-1`) with PostgreSQL **18**, database `triptab`, and a dedicated
generated-password role owning that database. The existing Neon project uses
PostgreSQL 18. Local Compose, backend CI, browser CI and disposable test databases
all target PostgreSQL 18. Local/CI images use `postgres:18-alpine`; provider patch
versions may differ within major 18. Local alignment uses a new volume and preserves
older clusters; see [volume preservation](persistence.md#triptab-local-naming-and-preserved-legacy-data).
Do not create Render PostgreSQL, enable paid add-ons, upgrade plans, or add a
payment method to bypass a free-plan limit without explicit approval. Check the
actual organization/workspace billing tier and overage controls before provisioning;
Render can bill bandwidth/build overages when a payment method is present.

Render uses Python 3.11 from `backend/.python-version` and locked production-only
`uv sync`. Free web services do not support `preDeployCommand`, shell/SSH or
one-off jobs. After CI is green for the exact release commit, an operator checks
out that commit locally and runs the following **one** migration step from
`backend/`, with production environment supplied securely outside Git:

```sh
uv run --locked --no-dev alembic upgrade head
```

Verify `alembic current` reports head (`20261003_0003` for the initial deployment)
and `alembic check` succeeds before manually triggering Render deployment of that
same commit. A failed migration stops the release. Never run migrations in a build
or web startup. Serialize releases and record the migration result; if a command
loses its connection, inspect the revision before deliberately retrying.
There are no new or edited schema revisions in M11. A git push must never deploy
new backend code before its required migration completes.

The service binds Render's `$PORT` on `0.0.0.0`, with one worker, one instance,
no reload, no raw access logs and no proxy-header trust. Its concurrency cap is
eight, preserving M10's limit and accommodating the trip screen's six concurrent
reads. A shared semaphore bounds password hashing, verification and rehashing to
two operations per process, retaining Argon2id library parameters. Over-capacity
HTTP requests receive Uvicorn's 503. Use `/health` for Render's periodic health
check so probes do not keep Neon compute awake. Check `/ready` on demand to
exercise database connectivity. Confirm startup, readiness, auth and a representative
workflow on the actual 512 MB service, inspecting memory/restarts before acceptance.
No persistent backend filesystem is needed.

For Vercel, create/use one TripTab project with Next.js preset, repository root
directory `frontend`, Node **22.x**, install `npm ci`, build `npm run build` and
framework-default output. The repository requires Node 22.22.2+ within major 22,
matching `.nvmrc` and CI. At release time, remove any Node 24 Production Override
so production inherits the Node 22.x project setting; confirm the resulting
deployment runtime is Node 22. Do not change provider runtime settings during
local milestone implementation. Set the server-only backend origin before building.
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
| Render `DATABASE_URL` | Secret direct Neon connection URI for `triptab`; standard `postgresql://` is normalized to psycopg without changing credentials or query options |
| Render `PGSSLMODE` | `verify-full`, verifying certificate chain and hostname |
| Render `PGSSLROOTCERT` | `system`, loading libpq/OpenSSL system trust roots |
| Render `PGCHANNELBINDING` | `require`, requiring SCRAM channel binding |
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

Use the direct Neon hostname (no `-pooler`) for runtime, Alembic and logical backups.
One service with the existing five-connection/no-overflow SQLAlchemy pool does not
need an additional PgBouncer layer. Keep pre-ping and bounded connection timeouts;
verify reconnect after Neon suspends. Neon Free uses a public TLS endpoint; private
networking/IP allowlisting are unavailable on this plan. Strong credentials and
certificate-verifying TLS are required. Do not use this role for unrelated data.

Set connection query options to `sslmode=verify-full&sslrootcert=system&channel_binding=require`
or omit them and use the libpq environment settings above. URI query options
override environment defaults: replace a provider-generated `sslmode=require`,
never leave it to override verification. Preserve encoded credentials. Native
PostgreSQL tools use `postgresql://`, not SQLAlchemy's `postgresql+psycopg://`.
The locked psycopg binary uses libpq 18 locally, which supports system roots.
Verify the installed client and actual Render connection, certificate/hostname
checks and channel binding before acceptance. A successful `/ready` with the
verified TLS options and required channel binding demonstrates that the deployed
client can authenticate securely; inspect only sanitized connection diagnostics.
The local Mac operator check required `SSL_CERT_FILE` to select the existing
trusted CA bundle returned by `ssl.get_default_verify_paths().cafile`; this keeps
`sslrootcert=system` and hostname verification. Do not copy that Mac path to Render.
Do not hard-code a Render CA filesystem path. If system roots are unavailable,
investigate the installed client/trust configuration without weakening TLS.

Live [Neon pricing](https://neon.com/pricing) and
[plan documentation](https://neon.com/docs/introduction/plans), checked **2026-10-10**,
currently report 100 CU-hours/project/month, 1 GB PostgreSQL storage/project,
5 GB public egress/project/month, 10 branches/project and a six-hour instant-restore
window capped at 1 GB of change history. Free scale-to-zero is mandatory after
five idle minutes. Do not enable paid snapshots or scheduled backups.
These are a dated pricing snapshot;
re-check live pricing and actual account/project limits at provisioning, and use
the reported values if they differ. Compute/egress exhaustion suspends compute;
storage exhaustion blocks writes. Limits do not delete existing data. No automatic
paid upgrade is permitted.

Verify the project's actual restore window after creation; pricing alone is not
backup evidence. After smoke data, produce a native PostgreSQL 18 `pg_dump -Fc`
logical export and validate a restore into an empty separate database. Use
PostgreSQL 18 clients for production and the local Compose drill. Keep the
destination on major version 18.
Create the destination explicitly; do not rely on dump/restore `--create` or `pg_dumpall` with
Neon. Use `pg_restore --no-owner --no-acl --exit-on-error`. Revoke restored sessions
before routing traffic to recovered data. Keep archives encrypted, restricted and
outside Git. The six-hour recovery window does not replace off-provider exports.
The operator owns daily and pre-release exports to existing protected storage;
no paid storage or scheduler is provisioned implicitly. See
[Neon PostgreSQL import](https://neon.com/docs/import/migrate-from-postgres) and the
[restore and session revocation procedure](operations.md#backup-and-recovery).

## Deployment ordering and CI gate

1. Pass local backend pytest/Ruff/Alembic check, frontend tests/lint/typecheck/build
   and existing Playwright flows against the local production build. Tests never
   point at production. Scan tracked files and Git history for secrets.
2. Commit repository changes, push and verify both GitHub CI jobs for the exact SHA.
   Use that immutable green commit for both provider deployments.
3. Reserve a Vercel project and its production alias without serving a preview as
   the product. Record its exact HTTPS origin, resolving the bootstrap dependency.
4. Use the existing Neon Free PostgreSQL 18 project; verify the plan, region,
   database, TLS and live limits. Supply its direct URL only through protected runtime secrets.
   Manually migrate from the exact green commit and verify head/check. Only then
   create/deploy the Render Free service (creation may start an initial deploy),
   supplying the reserved browser origin in `TRIPTAB_ALLOWED_ORIGINS`.
5. Confirm backend `/health`, `/ready`, migration head, one-worker/instance settings
   and safe logs. Set Vercel `TRIPTAB_API_ORIGIN` to that backend HTTPS origin.
6. Deploy Vercel production from the same green SHA. Check that the actual public
   alias exactly matches backend allowed Origin; deliberately correct and redeploy
   if the provider assigned a different alias. Never use a wildcard bootstrap.
7. Run the production checks below, inspect recovery/export capability and scan
   the repository again. Record actual URLs, provider IDs, deployed SHAs and evidence
   in the completion report without secrets.

All initial releases are **manual**. Render `autoDeployTrigger: "off"` and Vercel
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
- Confirm Neon Free plan, version, region, quotas, actual recovery window and
  completed initial logical export/restore. Verify Render stays Free, auto-deploy
  stays off, and memory/events show no OOM or repeated restarts during the workflow.

Observe Render service Events/deploy logs for failed builds/migrations, runtime
Logs for JSON requests, readiness health checks for DB availability, and the
database Metrics/Recovery pages for capacity and recovery. Vercel Deployments
and Observability/External Origins show frontend/rewrite failures. Availability
monitoring is provider-native; no external monitoring SaaS is added.

## Rollback and limitations

Record the previous accepted application releases and their compatible schema.
Redeploy/rollback to those Render/Vercel releases with the correct paired backend
origin. Keep automatic deploys disabled during rollback. Do **not** automatically
downgrade Alembic. M11 has no schema changes;
initial migrations create the existing schema. For future destructive migrations,
restore/PITR into a separate database, validate ledger/history and migration head,
revoke recovered sessions, then deliberately switch traffic. Account for writes
since the recovery point; retain the source until recovery is accepted.

The initial Vercel alias suffices; purchasing a custom domain is deferred. Adding
one requires deliberately updating allowed Origin and repeating cookie/CSRF/cache
checks. Current limitations include one-worker/instance fixed-window auth limiting,
shared proxy-IP buckets, small compute/storage, no HA guarantee, short recovery
retention and targeted rather than strict script CSP. Render Free sleeps after
15 idle minutes and can take about a minute to wake; Neon adds its own wake delay.
Verify cold-start/proxy timeout behavior and safe error handling; never automatically
retry a financial POST, because a timeout does not prove it was not committed.
Render Free has 750 running hours per workspace/month, ephemeral files, and can
suspend for unusually high outbound traffic to external databases. Observe free
bandwidth/build quotas and disable paid overages; Vercel Hobby is for personal,
noncommercial use and pauses features at limits. Restarts reset local rate-limit
counts but preserve database-backed sessions. Session cleanup, distributed
limiting, reset/verification/OAuth, multi-currency, OCR, recurring
expenses, analytics, idempotency, ledger versioning and payment integration remain
deferred. Development-only npm advisories acknowledged in M10 are not resolved
by this deployment; no breaking dependency changes or audit fixes are introduced.

Provider references: [Render Blueprint schema](https://render.com/docs/blueprint-spec),
[release commands](https://render.com/docs/deploys),
[Render Free limitations](https://render.com/docs/free),
[Neon TLS](https://neon.com/docs/connect/connect-securely),
[libpq system trust](https://www.postgresql.org/docs/18/libpq-connect.html#LIBPQ-CONNECT-SSLROOTCERT),
[Vercel external rewrite cache changes](https://vercel.com/changelog/vercels-cdn-now-respects-cache-control-headers-from-external-origins-by-default),
[cache header priority](https://vercel.com/docs/caching/cache-control-headers), and
[manual Git deployment configuration](https://vercel.com/docs/project-configuration/git-configuration).

## Pending Milestone 12

[Collaborative invitations](invitations.md) are implemented locally with additive
revision `20261011_0004`, but the deployed M11 baseline and head `20261003_0003`
remain unchanged. No M12 production resources, data or configuration are changed.
Release only after review, push, green CI and explicit production migration
approval, then manual Render/Vercel release; automatic deployment stays disabled.


## M20B release with recovery OFF

This is a future, separately approved release plan, not an implementation action.
Production remains on M19A / `20261012_0006`; M19B + M20A + M20B may be released
without transactional email. The repository head remains `20261012_0007`.

Set both gates OFF for that release:

| Environment | Variable | Value |
| --- | --- | --- |
| Render backend | TRIPTAB_PASSWORD_RECOVERY_ENABLED | false |
| Vercel frontend build | NEXT_PUBLIC_TRIPTAB_PASSWORD_RECOVERY_ENABLED | false |

The backend is authoritative. The frontend flag is visibility only and introduces
no extra Home request. Next.js embeds direct `NEXT_PUBLIC_*` references at build
time: changing the Vercel flag requires a new build/deployment, not merely changing
a running environment. Never expose provider keys through public variables.
See [Next.js environment variables](https://nextjs.org/docs/app/guides/environment-variables).

Keep Render automatic deployment OFF. Environment changes must be intentional:
choose **Save only** when staging, then manually deploy the approved exact commit.
Other save choices can deploy/rebuild immediately. See
[Render environment variables](https://render.com/docs/configure-environment-variables).

Release checklist:

1. Confirm the approved exact SHA and green CI; verify current production health.
2. Create an encrypted Neon PostgreSQL backup using the existing protected
   [backup procedure](operations.md#backup-and-recovery), outside Git.
3. Verify production is exactly `20261012_0006`; stop if the state differs.
4. Apply `20261012_0006 -> 20261012_0007` exactly once, then verify Alembic
   current/check and preservation of Users, Trips, financial history, sessions and
   invitations. Existing M19A application must remain operational before deployment.
5. Stage Render `TRIPTAB_PASSWORD_RECOVERY_ENABLED=false` without requiring
   `RESEND_API_KEY`, sender settings or DNS/Resend setup. Keep existing TLS,
   Origin/cookie/CSRF settings and the one-worker Free service.
6. Deploy Render at the approved exact SHA. Verify health/readiness, Registration,
   Sign in, Change password, financial APIs, and both recovery endpoints' generic
   503/no-store behavior with no state mutation or email.
7. Build/deploy Vercel at that SAME SHA with public visibility flag false and Node
   22. Verify Forgot password is hidden; both direct recovery routes are unavailable
   and clear reset fragments. Check M20A loading, auth, Trip navigation and finance.
8. Review logs for unexpected errors/migration issues and secret/token/password/key
   leakage. Confirm no real recovery email was sent. No paid resources/add-ons,
   resource recreation, automatic deploy or production SQL cleanup is authorized.

No production actions are performed by M20B implementation. Migration 0007's table
may remain dormant with both gates OFF; no schema/backfill/history changes are needed.

## Future password recovery activation

After separate approval:

1. Obtain a domain with DNS control.
2. Verify the sending domain with the exact DNS records supplied by Resend.
3. Create a dedicated Sending-only API key restricted to the sending domain.
4. Configure backend-only values below securely, keeping recovery OFF while staging.
5. Send one controlled provider-level test message to an address the operator
   controls. Verify actual receipt; do not create/consume a TripTab reset token.
6. Enable backend `TRIPTAB_PASSWORD_RECOVERY_ENABLED=true`; production refuses
   incomplete/invalid email configuration. Apply through a deliberate manual deploy.
7. Enable frontend `NEXT_PUBLIC_TRIPTAB_PASSWORD_RECOVERY_ENABLED=true`.
8. Rebuild/deploy at the approved SHA with Node 22; flag changes are not runtime toggles.
9. Run a disposable-account recovery smoke: generic known/unknown 202 responses,
   received fragment-only links, password-policy rejection preserving the token,
   valid passphrase reset, all-session revocation, explicit Sign in, old-password
   rejection/new-password acceptance, single-use and latest-link-wins. Review safe logs.

| Backend-only variable | Required value when enabled in production |
| --- | --- |
| TRIPTAB_PASSWORD_RESET_EMAIL_PROVIDER | resend |
| RESEND_API_KEY | Provider secret, only in protected backend configuration |
| TRIPTAB_PASSWORD_RESET_FROM_EMAIL | Bare email address on the verified sending domain |
| TRIPTAB_FRONTEND_BASE_URL | https://triptab-hazel.vercel.app, matching allowed Origins |

The adapter adds `TripTab <...>` to the bare sender. Domain ownership/verification
must be confirmed externally; the shared Vercel hostname is not an assumed sending
domain. Preserve original fragment-bearing reset URLs and disable click/open
tracking; no redirect/analytics wrapper or marketing template is needed. Do not
interpret enabled-mode generic 202 as proof of actual email delivery. Provider
setup, real email, paid upgrades and activation are not performed in this milestone.
