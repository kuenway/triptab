# Collaborative trip invitations

Claiming a Guest links an account to an **existing financial identity**. It does
not create or migrate a financial identity. User is an account/recording actor;
GroupMember is a traveler in one trip. The target member's UUID, display name,
member role, expense payer references, split allocations, settlements, and
correction/void history remain unchanged. Only `GroupMember.user_id` becomes the
accepting account ID. Balances and suggestions therefore remain identical at
claim time. Other travelers may remain Guests.

## Permissions and API

All paths start with `/api/v1`. Authenticated mutations retain session-bound CSRF
and exact Origin checks. The backend, rather than button visibility, authorizes
operations. An unlinked Guest cannot access the trip.

| Endpoint | Permission / behavior |
| --- | --- |
| `POST /groups/{group_id}/members/{member_id}/invitations` | Owner only; target must be an unclaimed member in that trip. Returns metadata and raw token once. |
| `GET /groups/{group_id}/invitations` | Owner only; newest first, metadata/status only, never token or digest. |
| `POST /groups/{group_id}/invitations/{invitation_id}/revoke` | Owner only; revokes pending invitation without deleting it or changing its Guest. |
| `POST /invitations/preview` | Allowed Origin, optional authentication; token in body. Returns only trip name, target display name, expiry. |
| `POST /invitations/accept` | Authenticated, CSRF-protected explicit confirmation; token in body. Returns the claimed existing member. |

Unauthenticated acceptance/management is 401. A linked member without owner
permission gets 403; outsiders and mismatched nested trip/member/invitation IDs
get 404. Invalid, expired, revoked or consumed preview links return the same safe
404 unavailable response. Acceptance of an already-consumed token by a different
account, an already-linked target, or another identity in the same trip returns
409. Malformed bodies return safe 422 without echoing tokens. Every invitation
API response, including public preview/errors, retains API `no-store` headers.
Token possession grants minimal preview, never ledger access or an account bypass.

After acceptance the account uses the existing normal Member permissions:
read the shared ledger, create expenses, record payments as linked sender/recipient,
and correct/void its own authored records. Owners keep their existing override.
A Member cannot add Guests or manage invitations. Recording User and financial
payer remain independent: Bob may record a valid expense paid by Guest Charlie.
No email directory, account search, ownership transfer or identity merging exists.

## Bearer security and lifecycle

`secrets.token_urlsafe(32)` supplies 256 random bits. The new `trip_invitations`
table stores only SHA-256 of the bearer token, with a unique digest. It also stores
UUIDs for trip/target/creator and creation/expiry, acceptance/accepting User, and
revocation/revoking User timestamps/metadata. It does not store a redundant status.
Accepted and revoked are terminal states; otherwise expiry determines expired
versus pending. `INVITATION_LIFETIME` is centralized at seven days. No cleanup job
is needed. Reissue revokes all unconsumed, unrevoked prior invitations for the same
Guest in the same transaction, including expired ones; old links cannot be reused.
If a newly created link is closed or lost, issue a new invitation. Raw links cannot
be retrieved later. Accepted invitations cannot be revoked or used by another User.

Raw tokens use secret request types; validation responses omit input/context.
Application request logs record route templates/status/request IDs, not bodies,
queries, invitation links, token digests or exception arguments. Invitation IDs
are safe metadata. No raw token belongs in logs, documentation or persistent
frontend storage. SQLAlchemy keeps parameters hidden in diagnostics.

## Fragment and authentication flow

The owner sees Invite to TripTab, invitation state and pending Revoke controls in
the traveler section. Creating shows a copyable link with path `/invite` and
fragment `#token=…`. It remains only in that component's memory until closed or
unmounted. Other members do not fetch or see invitation-management metadata.

The `/invite` page reads the fragment client-side, checks its format and previews
using the centralized typed API client. Fragment contents are never part of the
HTTP request URL, so they do not enter Vercel/Render URL logs. No query/path token
or browser-side cross-origin API is used. Authenticated invitees confirm Join as
the target Guest; acceptance is never automatic.

For logged-out invitees, Log in to join / Create account to join carry the same
fragment onto the normal login/register page. Switching auth forms preserves it.
These navigations replace the current history entry. Successful authentication
scrubs that auth page's fragment and replaces it with `/invite` plus the fragment,
where the User must explicitly confirm joining. Acceptance/cancellation clears
React token state and the current fragment, then replaces the page with the trip
or home. No localStorage or sessionStorage is needed. Errors retain context for
an explicit retry; there is no automatic mutation retry. Stale preview responses
are ignored when another invitation fragment is selected.

## Atomic claiming and races

All state transitions lock the target GroupMember row before locking/updating
invitation rows. Acceptance re-reads the invitation under that lock and revalidates
terminal state, expiry, target association and the User's existing membership.
The member's account association and invitation acceptance metadata commit in one
application-owned transaction. Failures roll back both, never financial rows.
Localized row locks serialize create/reissue/revoke/accept for the same target;
no distributed lock or generic idempotency framework is introduced.

Two different Users racing for the same invitation yield one success and one clean
409. The same User retrying an accepted invitation gets the original successful
member result, including after the former pending expiry, provided it is still
linked to that User. Competing claims by one User for two distinct Guests also
cannot create duplicate memberships: the existing `(group_id, user_id)` unique
constraint is the final defense and its violation is translated to safe 409 after
rollback. No merge or financial identity movement occurs. Revocation/reissue that
commits first makes a waiting acceptance unavailable; acceptance that commits first
prevents later revocation/reissue of that claimed target.

## Schema and release boundary

New revision `20261011_0004` follows production head `20261003_0003` and adds only
the invitation table/index. Composite foreign keys scope target to trip; actor
foreign keys restrict deletion. Checks require valid digest/expiry, paired
terminal timestamp/actor fields, valid lifecycle times and mutually exclusive
acceptance/revocation. Membership uniqueness and all financial constraints remain.
Downgrade is disposable-only: it drops invitation audit, not member account links
or financial history. It is not an identity undo.

M12 is verified only on local Docker Compose PostgreSQL. It does not deploy, push,
run production migrations, change provider configuration, or create production
invitations. Release requires review, push, green CI, explicit production migration
approval, then the existing manual backend/frontend deployment procedure. Keep
Render automatic deployment disabled. No invitation cleanup worker, email delivery,
unrestricted join link, identity merge or membership removal is included.
