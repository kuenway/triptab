# Foundation decisions

These are the approved product constraints for future milestones. Milestone 0 does
not implement the related domain behavior.

- v0.1 supports TWD only, stored as integer NTD (`currency_scale = 0`).
- `GroupMember` may represent a guest without a registered account.
- Expense and settlement history is immutable; corrections use void and replacement
  records.
- Initial split strategies are Equal and Exact.
- Balances are calculated from history, not stored as mutable user balances.
- Keep idempotency, ledger versioning, and concurrency controls in the architecture;
  implement them when a milestone introduces a concrete need.
- Frontend tests start when frontend logic exists. Add an end-to-end test when an
  end-to-end user flow exists.

Milestone 8 implements immutable history with separate void rows. Replacement
links live on those rows, and balances use effective records selected before
accounting. Audit metadata extends existing retrieval responses and history
sections; no combined timeline or generic event-sourcing layer is needed.

Milestone 9 adds first-party Argon2id accounts, PostgreSQL opaque sessions,
explicit Secure-cookie configuration, session-bound CSRF tokens and Origin checks,
and account-linked owner/member authorization. New groups create owner membership
atomically. Legacy financial history is retained without inventing ownership.
Inviting/linking additional registered members is deferred; owners can add guests.

Milestone 10 adds validated production configuration, readiness, allowlisted JSON
request logs, browser headers and bounded process-local authentication rate limits.
The initial deployment uses one backend worker. Releases migrate once before
traffic; recovery uses native PostgreSQL backups into a separate database.
Containers and hosting remain deferred. Financial, account and authorization
semantics and all pushed migrations remain unchanged.

Milestone 12 implements owner-issued invitations to claim existing Guest member
identities. Tokens are 256-bit bearer secrets, persisted only as SHA-256 digests;
links use URL fragments, with explicit authenticated acceptance. Target member row
locks and existing membership uniqueness protect races. Accounting and financial
identity/history do not change. Production release remains separately approved;
see [invitation contracts](invitations.md).
