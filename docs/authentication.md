# Authentication and group access

TripTab uses first-party email/password accounts and opaque PostgreSQL sessions.
All financial product routes under `/api/v1/groups` require authentication.
`/health`, registration, and login are public; public authentication POSTs still
require an allowed Origin. Production was deployed in M11; M12 invitations await
a separately approved release.

## Accounts and passwords

Email is trimmed, validated using Pydantic/email-validator, and lowercased before
storage or login lookup. PostgreSQL enforces normalized values and unique email.
Registration requires a 12–128 character password and a nonblank display name up
to 100 characters. Passwords are never trimmed, logged, or returned. Pydantic
`SecretStr` masks their representation, and validation responses omit submitted
inputs and validation context, which can otherwise contain secrets.

Password hashing is infrastructure, separate from financial domain objects.
`argon2-cffi` uses its maintained `PasswordHasher` Argon2id defaults, random salts,
and library verification. Login rehashes when the library's parameters change.
Missing accounts and historical users without credentials verify a dummy hash
and receive the same 401 `invalid email or password` response as a wrong password.
See the [Argon2 library API](https://argon2-cffi.readthedocs.io/en/stable/api.html).
M9 did not include email verification, recovery, OAuth, a user directory, or
disabled-account management. M19B adds the focused recovery flow below.

M10 centralizes configuration and adds bounded authentication rate limits, safe
request diagnostics and production safeguards without changing these semantics.
See [operations](operations.md) for configuration and limits.

## Sessions and cookies

A successful registration or login generates a 256-bit random opaque session
bearer token with `secrets.token_urlsafe(32)`. Only its SHA-256 hash is stored in
`auth_sessions`, along with a UUID, user ID, creation time, seven-day expiry,
revocation time, and an independent random CSRF token. Raw bearer tokens are
never stored in PostgreSQL, returned in JSON, or logged. There are no JWTs.

Login and registration issue a fresh session and revoke the previous session
presented by that browser. Failed login leaves the existing session unchanged.
Logout revokes the current session and clears its cookie. Expired/revoked sessions
may remain stored; authentication rejects them. GET requests never extend sessions
or modify state. No scheduled cleanup, Redis, or background worker is needed.

The host-only `triptab_session` cookie is explicitly `HttpOnly`, `SameSite=Lax`,
`Path=/api/v1`, and `Max-Age=604800`. `Secure=true` is the default when
`TRIPTAB_COOKIE_SECURE` is absent; only explicitly setting it to `false` permits
local HTTP development. There is no automatic insecure fallback based on Host or
proxy headers. Root `.env.example` supplies the local override. Keep this override
out of a future HTTPS environment. Authentication responses use `Cache-Control:
no-store`. The browser stores the bearer token only in its HttpOnly cookie, never
in React state or local/session storage.

`get_current_user` is the canonical authentication dependency. It hashes the
request cookie and loads a valid, non-revoked, unexpired session and credentialed
User. Its short read session closes before the financial use case starts its
caller-owned transaction. Product routes receive a `TripTabService` with a
required current User; there is no actor fallback.

## CSRF and Origin protection

SameSite is an additional defense, not the entire CSRF mechanism. Each server-side
session has an independent, unpredictable synchronizer CSRF token. Register,
login, and `GET /api/v1/auth/me` return `{user, csrf_token}`. The frontend retains
only the CSRF token in the API client's memory and sends it as `X-CSRF-Token` on
all authenticated state-changing requests. A reload bootstraps it through `/me`.
The backend compares it to the current session's token using a constant-time
comparison; another session's token cannot authorize a write.

All authenticated POST/PUT/PATCH/DELETE requests must also provide an exact allowed
`Origin`, including scheme, host, and port. Registration and login require this
Origin check too, preventing login CSRF before a session exists. Missing, `null`,
and unlisted Origins are rejected. `TRIPTAB_ALLOWED_ORIGINS` is a comma-separated
explicit allowlist; its absent/empty default rejects mutations. Browser fetch
supplies Origin automatically. Command-line clients must provide the configured
Origin and, for authenticated mutations, the session CSRF header.

No cross-origin credentialed CORS access is enabled. The frontend uses its own
origin and Next.js rewrites `/api/v1` to the backend. CSRF handling is centralized
in the typed client, rather than repeated in forms. See the
[OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).

## Membership, guests, and permissions

User identity is not GroupMember financial identity. A User can have one linked
GroupMember per trip, enforced by `(group_id, user_id)` uniqueness. Creating a
trip atomically saves the Group and the current User's owner GroupMember. The
owner is an ordinary financial participant with the extra `owner` role. Guest
travelers have no User, retain independent financial identities, and cannot log
in or gain access by knowing a trip UUID. Guests default to `member` role.

A partial unique index permits at most one owner per group; a check requires the
owner to be account-linked. The application creates an owner for every new trip.
Legacy groups may have no owner. Normal account-linked memberships have `member`
role. M9 intentionally offered only owner-account creation and adding guests;
inviting/linking additional registered accounts had no public endpoint then. M12
adds [explicit Guest invitation claiming](invitations.md). Tests
establish registered member fixtures explicitly to verify their permissions.

| Operation | Allowed |
| --- | --- |
| List trips | Only current User's account-linked trips |
| Read trip, members, expenses, payments, balances, suggestions, audit history | Account-linked members of that trip |
| Add guests | Owner |
| Create/list/revoke Guest invitations | Owner |
| Claim an invited Guest | Authenticated User with valid token, CSRF and Origin; no existing trip membership |
| Create expense | Any account-linked member |
| Record payment | Owner, linked sender, or linked recipient |
| Void/correct expense or payment | Original recording author or owner |

Correction requires original-author/owner permission. A replacement payment is
also a new payment, so the current User must be its linked sender, linked
recipient, or group owner. This prevents corrections from bypassing recording
permissions. Complete replacements receive the current actor and normal financial
validation. Owners may record transfers between guests. Actors always come from
the authenticated User; client-supplied actor/user/role fields are rejected. Responses add
`created_by_user_id` for permission-aware UI while retaining original financial
values, history metadata, and ordering. Member responses add `role`; member lists
do not reveal account email addresses.

The application checks membership before scoped nested lookups. A target from
another trip cannot be used under an authorized trip URL. Unauthenticated calls
return 401. An inaccessible or missing trip, or a mismatched nested resource,
returns 404 without revealing private trip existence. A linked member lacking
write permission gets 403. Existing financial validation (422) and already-voided
conflicts (409) are unchanged. UI visibility is convenience; the backend enforces
all rules independently.

## Legacy development data and migration

Revision `20261003_0003` upgrades the M8 head. It normalizes existing user emails,
adds nullable password hashes, membership roles/constraints, and `auth_sessions`.
It preserves all financial rows, user IDs, void records, and replacement links.
If historical user emails collide after normalization, the migration deliberately
fails transactionally rather than merging identities; resolve such duplicates
manually before retrying. Existing users with NULL hashes cannot authenticate and
registration cannot claim an existing email. No ownership is invented for guests.

Historical financial records retain their old development actor IDs.
`DEVELOPMENT_ACTOR` has no application or test runtime fallback. Existing legacy
trips without account-linked access remain inaccessible to newly registered users.
For expendable local data, recreate the development database and migrate afresh;
for history you need, explicitly review and manually establish the correct account
membership/owner and credentials. Do not rewrite historical financial actor IDs.
There is no automatic legacy ownership or group claiming. M12 permits explicit
owner-issued invitation claims for existing Guests only.

Downgrade to M8 is for disposable databases only: it discards password hashes,
sessions, and roles while retaining financial history and user IDs. It is not a
financial undo or an account migration strategy.

## Local workflow and tests

For a new checkout, copy root `.env.example` to `.env`. For an existing `.env`,
add these explicit local settings:

```dotenv
TRIPTAB_COOKIE_SECURE=false
TRIPTAB_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

Start Compose PostgreSQL, then from `backend/`:

```sh
uv sync --locked --python 3.11
uv run --env-file ../.env alembic upgrade head
uv run --env-file ../.env alembic check
uv run --env-file ../.env uvicorn app.main:app --reload --port 8000
```

Start the frontend as documented in README. Open `/register`, create Alice's
account, create a trip, and add Bob and Charlie as guests. Alice already appears
as Owner; do not add a second financial identity for her. Record expenses or
payments, log out, and log back in through `/login`. Private routes redirect to
login while logged out; expired API sessions clear frontend current-user state.
A failed authentication connectivity check offers retry without treating it as a
confirmed logged-out state.

The integration suite uses isolated real PostgreSQL transactions and actual cookie
sessions. Existing financial API regressions create authenticated-owned trips.
Playwright uses a separate `*_e2e_test` database, explicitly permits the HTTP
frontend at `http://127.0.0.1:3100`, and tests logout/login, private trip isolation,
and correction history. Browser tracing is disabled to keep authentication
credentials and session cookies out of trace artifacts. CI continues using real
PostgreSQL with the existing jobs; no new service infrastructure is added.

M13 adds Owner-only unused Guest removal with the existing session, Origin and
CSRF checks. Linked Members (including accepted invitees) cannot be removed in
this milestone. Owner overrides do not permit deleting financial identities.
Frontend Expense defaults use the authenticated User's linked GroupMember as
payer, with explicit editing allowed; a missing association never falls back to
an arbitrary traveler. Recording actor still comes exclusively from the session.

## M19A account settings

`User.display_name` already represents account identity; M19A reuses it rather
than adding another profile field. Revision `20261012_0006` makes it nullable
without changing existing values or backfilling email-derived names. A null name
is valid. Non-null names are trimmed, Unicode-friendly, case-preserving and
1–100 characters; account names have no uniqueness requirement. Registration
still requires a name. `GroupMember.display_name` remains a separate, non-null,
Trip-specific financial label. User identity is not GroupMember identity.

`GET /api/v1/auth/me` retains `{user, csrf_token}` and allows a null account name.
`PATCH /api/v1/auth/me` accepts only `display_name` (null clears it), requires
authentication, Origin and session CSRF, and returns the same representation.
Unknown fields, including email, user IDs and password fields, are rejected.
Email is read-only and remains the sign-in identifier. Responses stay `no-store`.

Account names default the Owner GroupMember name only when creating a **new**
Trip. A null account name uses the existing email-based presentation as a
creation fallback (email local part); it is not persisted back to the account.
Changing an account name never renames existing Tripmates or financial history.
Accepting an invitation links the existing Guest UUID without changing its name:
an account called Robert Chen still claims the Tripmate Bob as Bob. No name
matching, bulk synchronization or financial identity migration occurs.

`POST /api/v1/auth/change-password` accepts `current_password` and `new_password`.
The authenticated session requires Origin and CSRF. It reuses registration’s
12–128 character password policy, Argon2id defaults, bounded password work, and
the existing shared process-local auth limiter (no new distributed service).
Incorrect current password returns 422 with a safe field message, not logout/401.
Password change locks the User, revalidates the current Session UUID, verifies
the old password, hashes the new password, and revokes every other unrevoked
session in one transaction. The current cookie, session and CSRF token remain
valid; other Users’ sessions are unaffected. Login takes the same User lock so
a concurrent old-password login cannot bypass revocation. No password, hash or
session secret is returned or logged. Success returns 204.

The protected `/account` page is reachable through the Home account menu and
returns to All trips; it has no Trip navigation. Saving a name updates the
existing auth state without reloading the session. The menu uses the name initial
or its existing email fallback. Native password fields support password managers
and paste; passwords live only in transient form state, never browser storage
or URLs. Confirmed success clears them. An uncertain network/5xx result blocks
resubmission and explains that the password may already have changed; verify
with a separate sign-in before retrying. Profile uncertainty offers a read-only
account recheck instead of automatically repeating the mutation.

Downgrade is limited to disposable/reviewed databases and deliberately refuses
when null account names exist; it neither invents names nor discards accounts.

## Password recovery (M19B)

`POST /api/v1/auth/forgot-password` accepts a normalized email and always returns
202 with the same generic message for known, unknown, null-name and
non-login historical accounts, including when delivery fails. It returns no token,
identity or delivery status. Only credentialed accounts can recover. Public auth
POSTs require the exact allowed Origin but no existing session or session-CSRF
header. `POST /api/v1/auth/reset-password` accepts only `token` and `new_password`;
it reuses registration's SecretStr 12–128 character policy and the existing
Argon2id hasher/two-operation semaphore. No password trimming or weaker hashing.

Reset tokens use `secrets.token_urlsafe(32)` (256 bits, 43 URL-safe characters).
Only the existing SHA-256 digest utility's output is stored, with UUID, User FK,
UTC creation/expiry, used_at and revoked_at. Lifetime is 30 minutes, checked by
the server without extension. Revoked_at distinguishes replacement/delivery
failure from actual use. Requesting another link revokes prior unused tokens;
successful reset consumes its token and revokes every remaining unused token.
Token hashes are unique/indexed; a database trigger protects token ID, ownership
and digest from reassignment. There is no cleanup job or token recovery endpoint.

All account mutations serialize on **User first**. Reset discovers user_id from
its digest without taking a token lock, locks the User, then locks/reloads the
reset-token row and revalidates expiry/use/revocation. Password update, token
consumption/invalidation and **all** session revocations commit together. Concurrent
use of the same token yields one 204 and one neutral 400. Invalid, expired,
replaced or consumed tokens share `This reset link is invalid or has expired.`
No token IDs or account data appear in errors. Transaction failure changes none
of those states. Recovery never creates a session and clears the requesting
browser's session cookie; the user must explicitly Sign in afterward.

Login and M19A Change password keep their existing User lock. An old-password
login that commits before reset has its session revoked by reset; one arriving
second verifies against the new hash and fails. If recovery commits first,
Change password's current-session revalidation rejects its revoked session. If
Change password commits first, an otherwise valid recovery token can still reset
that account and revoke all sessions. This intentional distinction preserves
email recovery authority; merely opening an old email changes nothing, and a
superseded/consumed link can never undo a newer reset. Authenticated Change
password continues preserving its current session and revoking the others.

Forgot/Reset reuse the shared IP/global process-local auth limiter. Forgot also
limits each SHA-256-normalized-email target to three requests per shared window,
including unknown targets and across callers; the global limit bounds this map.
429 and Retry-After do not reveal account existence. One worker/instance remains
the operating assumption; no Redis, queue or worker is introduced.

### Delivery and browser boundary

Token creation/replacement commits before FastAPI's built-in post-response email
task. Provider I/O therefore does not delay the generic response or hold a User
lock. This is an in-process, non-durable task, not exactly-once email delivery:
process interruption can lose delivery, and the user may request a new link.
Provider failure logs only request ID/category and revokes that specific unused
token under User-first ordering. A late failure cannot revoke a newer link or
invalidate a consumed token. If invalidation itself fails, a second safe event is
logged; the bearer remains undisclosed and still expires normally.

The focused sender Protocol has a Resend adapter using Python's standard HTTPS
client, a fixed `api.resend.com` host, verified system trust, a 10-second timeout,
no redirects and no automatic retry. Minimal plain-text email includes only the
reset link, expiry and ignore-if-unrequested guidance. Provider replies, email
bodies, recipients, tokens, hashes and passwords are never logged. The adapter
follows [Resend's send-email API](https://resend.com/docs/api-reference/emails/send-email).
Production setup is a separate release task; see deployment/operations docs.

`/forgot-password` is public and uses the existing auth shell with identical
confirmation for known/unknown emails. `/reset-password#token=...` captures the
fragment into component memory, then removes it from the address bar. It never
uses query parameters, cookies, localStorage or sessionStorage. Reloading after
capture loses the token; reopen the email link or request another. Missing or
unavailable links show one neutral recovery state. New/confirm password fields
support password managers and paste. Confirmed success clears secrets and offers
Sign in, never automatic authentication. Unknown network/5xx outcomes clear
secrets and require checking Sign in before requesting another link, without
automatic retry. Recovery pages are dynamically served no-store with the existing
no-referrer/CSP headers and no analytics. Opening them does not mutate sessions;
successful recovery revokes every session of the recovered User, including their
current one. Other Users' sessions remain valid. Existing invite fragment
continuation remains unchanged; after a separate email recovery, reopen the
original invitation to continue claiming its existing Guest identity.

Local/unit/integration tests inject fake senders; no real email is sent. The
browser harness is under backend/tests, absent from the packaged app, and refuses
anything except TRIPTAB_ENV=test with a local *_e2e_test database. Its in-memory
mailbox/controlled-expiry routes exist only in that test app, never app.main.

Email changes/verification, account deletion, administrator resets, support
password overrides, magic links, OAuth, MFA, photos, and general notifications
remain deferred. No production provider account, key, DNS or environment is
configured by this implementation.


### Shared new-password policy (M19B final review)

Registration, Change password and recovery all call validate_password_policy.
Its structural policy is 12–128 characters; the API uses the same constants.
Account-context checks reject email-equivalent passwords using the established
strip().lower() email semantics (comparison only), and new passwords verified
against the current Argon2id hash. Password bytes are never trimmed/lowercased
for hashing or login. Unicode, spaces and passphrases are allowed; uppercase,
numbers and symbols are not required. No history or rotation policy exists:
A -> B -> A is allowed, while B -> B is rejected.

Change verifies the supplied current password first, then validates the new one
under the User lock. Recovery resolves/revalidates its token and User first, then
validates against the current hash under that same lock. Argon2 verification and
hashing reuse the bounded semaphore without nested acquisition. Policy rejection
returns safe 422 feedback, changes no password/session state and does not consume
or revoke the reset token. The user can correct the form with that same token
until ordinary expiry/replacement/use makes it unavailable.

Tool review: the installed Pydantic and argon2-cffi primitives cover this policy.
[zxcvbn-python](https://pypi.org/project/zxcvbn/) 4.5.0 (Feb 2025, MIT, approximately
409 kB wheel, no declared dependencies) reports testing on Python 3.8–3.13; it is
useful for advisory estimates but defaults to 72 characters and warns about
longer input processing. Mandatory scoring would exceed this product decision.
[Django CommonPasswordValidator](https://docs.djangoproject.com/en/5.2/topics/auth/passwords/#django.contrib.auth.password_validation.CommonPasswordValidator)
provides a maintained local 20,000-password list. Its BSD-3-Clause 5.2.15 package
supports Python >=3.10 but brings an approximately 8.3 MB framework plus
asgiref/sqlparse. Copying a list instead needs deliberate data/license/update
ownership; no blocklist is adopted for this narrow policy.
[password-validator](https://pypi.org/project/password-validator/) is small
(approximately 5.7 kB, MIT, Python 3 wheel, no declared dependencies) but its last
release is May 2020 and advertised Python classifier stops at 3.7. It adds no
needed value over the existing length checks and does not solve account-context
Argon2 comparison. [Pwned Passwords](https://haveibeenpwned.com/API/v3#PwnedPasswords)
is a possible future breached-password check via hash-prefix range lookup or
local downloaded data; no external password service/data is used here. No new
dependency is added and no general strength claim is made by these minimal rules.
