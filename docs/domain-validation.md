# Domain validation boundary

The Python objects in `backend/app/domain/` validate facts available within one
object. Pure functions in `backend/app/accounting/` validate supplied group context
and financial history. Neither layer queries a database.

| Entity-local checks | Contextual or accounting checks |
| --- | --- |
| IDs have UUID shape and required text is nonblank | A referenced user, group, or member actually exists |
| Group currency is TWD with scale 0 | Supplied members and transactions belong to the same group |
| Expense amount is a positive integer NTD value | An expense has at least one valid participant |
| Split amount is a nonnegative integer NTD value | Split member IDs are unique and allocations total the expense amount |
| Expense strategy is Equal or Exact | Exact splits total the expense; Equal splits use the stable member-ID remainder rule |
| Settlement amount is positive and sender differs from recipient | Settlement members belong to the group; balances reflect the transfer |
| `occurred_at` and `created_at` are timezone-aware | The application sets trustworthy `created_at` and actor values |

An `Expense` carries final allocation records but does not calculate or certify
them. Its payer is a separate member ID from the split participant IDs; the payer
may be absent from the splits. `occurred_at` describes the real-world event, while
`created_at` records when the application entered it. Neither object generates a
timestamp or requires those two times to be equal.

There is no stored balance on `User` or `GroupMember`. The accounting layer derives
balances from valid, explicitly supplied history and includes every supplied group
member, even if their balance is zero. A later application layer must supply all
relevant historical members and trusted records. Financial corrections use separate
immutable `ExpenseVoid` and `SettlementVoid` values and replacement financial
records. Void values check UUIDs, a nonblank reason, aware recording time, and a
replacement ID different from the target. The application checks scoped existence
and active status; database keys enforce at most one void per target and
same-group replacement references. Original financial domain contracts are
unchanged. Effective-record selection belongs to persistence/application, before
pure accounting runs.

`GroupMember.role` is owner or member; an owner must be linked to a User. The
application enforces membership and recording permissions before financial
lookups and writes. Password hashes and login sessions are infrastructure, not
financial domain fields. Safe User values never carry credentials. Actor IDs are
trusted only when supplied by the canonical authenticated-user dependency.

Invitation lifecycle and Guest account claiming belong to application/persistence,
not accounting. Claiming changes only an existing GroupMember's nullable user
association; its UUID, role and financial references remain stable. Owner permission,
trip-scoped target, pending lifecycle and one-member-per-account checks are
contextual and transactional. See [invitations](invitations.md).

Guest removal is a transactional application/persistence rule: Owner only,
unclaimed non-Owner target, and no persisted financial references of any state.
Current zero balance does not prove eligibility. Revoking/detaching invitations
and deleting the unused target are atomic; snapshot and live-reference constraints
preserve retained audit. Accounting allocations and derived balances are unchanged.

New traveler names are unique within a Trip through the application creation
workflow. `canonical_traveler_name` uses exactly `display_name.strip().lower()`;
visible names retain their trimmed casing. No Unicode transliteration, casefolding,
or fuzzy matching is applied. All existing travelers, including the Owner and
account-linked Members, reserve their canonical name. A name can be reused in a
different Trip. Owner-authorized Guest creation locks the Group row in the same
transaction before reading names and inserting, so concurrent application requests
cannot both create a canonical duplicate. Duplicate requests return 409 without
creating a member. PostgreSQL's normal READ COMMITTED isolation ensures the next
creator reads members committed by the preceding holder of the Trip lock.

Existing duplicate names remain valid separate GroupMember UUID identities. No
rename, merge, history transfer, or automatic cleanup occurs. Removal checks still
use group/member UUIDs exclusively, include zero-valued splits and void/correction
history, and never infer eligibility from a balance or display name. Traveler action
errors are displayed on the row identified by the member UUID. Rejected removal
request logs include only group/member UUIDs and an internal rejection category
alongside existing request diagnostics; no names, financial details, or bodies.

Database-level name uniqueness is deferred because production may contain existing
canonical duplicates. Direct SQL or any future creation path that bypasses the
Trip lock and validation can still introduce duplicates. Before a future migration,
explicitly inspect and resolve duplicates without silently changing financial
identities; then backfill a stored canonical-name value using this exact application
normalization contract and enforce `(group_id, canonical_name)` uniqueness. A
PostgreSQL `lower(...)` expression must not substitute potentially different
normalization semantics. No schema change is part of Milestone 16.
