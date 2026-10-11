# Accounting rules

`backend/app/accounting/` is pure Python. Callers pass a `Group`, its relevant
`GroupMember` values, and financial records. The functions do not load, mutate, or
persist records. They raise `AccountingValidationError` for invalid allocations or
group history.

## Allocation and validation

- `allocate_equal(amount_minor, participant_ids)` returns final `ExpenseSplit`
  values in ascending UUID order. It divides whole NTD equally, then gives one
  remaining NTD to each lowest-ID participant until the remainder is exhausted.
  Thus NT$100 across three participants is `34, 33, 33`, independent of input order.
  Zero allocations remain present when there are more participants than NTD.
- `validate_exact_splits(amount_minor, splits)` accepts unique participants with
  nonnegative integer NTD allocations only when their sum equals the positive
  expense amount. It returns the supplied values in stable member-ID order and
  never repairs a mismatch.
- `validate_expense(group, members, expense)` requires the payer and every split
  participant to belong to that group, at least one unique split, and the split
  total to equal the expense amount. Equal expenses must carry the canonical
  allocation above; Exact expenses must carry valid final amounts. The payer
  need not be a participant.
- `validate_settlement(group, members, settlement)` requires both transfer members
  to belong to the supplied group. The domain object itself requires a positive
  amount and different sender and recipient.

## Balances

`calculate_balances(group, members, expenses, settlements)` validates all supplied
history and returns an integer NTD net balance for each supplied member, including
zero-balance members:

```text
net = expenses paid - expense allocations
    + settlements sent - settlements received
```

Positive means the member should receive money; negative means they owe money.
For a settlement where B pays A, B's balance increases and A's decreases. Partial
payments and overpayments are reflected as actual transfers; overpayments may
reverse a balance's sign.

Every valid expense has allocations totaling its amount. Each expense and
settlement changes the group-wide balance total by zero, so the sum of all member
balances is zero. Duplicate expense IDs, duplicate settlement IDs, and records or
members from another group are rejected. Recalculating the same supplied history
yields the same result.

The caller must include historical members referenced by financial records.
Inactive-member selection, generic idempotency and ledger versions remain deferred.
The application loads effective persisted history before calling accounting;
duplicate voids are protected by database uniqueness. M17C serializes all financial
mutations within a Trip, as described below.

## Settlement suggestions

These values have different meanings:

- A **balance** is a member's current net financial position derived from history.
- A **SettlementSuggestion** is an immutable proposed transfer with
  `from_member_id`, `to_member_id`, and positive integer NTD `amount`. It has no
  payment identity, timestamps, or recording actor and is never persisted.
- A **Settlement** records a real-world payment that occurred. Only these actual
  transfers affect the balance formula above. Reading suggestions changes neither
  financial history nor balances.

`suggest_settlements(balances)` takes a UUID-to-integer mapping whose total must be
zero. Noninteger balances (including booleans), invalid member IDs, and nonzero
totals raise `AccountingValidationError`. Zero-balance members are ignored; an
empty or all-zero mapping returns no suggestions.

Debtors and creditors are sorted separately by descending original balance
magnitude, then ascending UUID. The algorithm matches the current debtor and
creditor for `min(debt_remaining, credit_remaining)`, advancing either side when
it reaches zero. Ordering is fixed at the start; remaining amounts are not
re-sorted. Input insertion order does not affect the resulting tuple, and the
input mapping is not mutated. All arithmetic uses integers.

Every sender starts with a negative balance and every recipient with a positive
balance. Transfer amounts are positive, sender and recipient differ, and applying
the proposed transfers increases sender balances and decreases recipient balances
until every supplied balance is zero. Each transfer conserves the group total.

This greedy matching produces deterministic settlement suggestions; it does **not**
guarantee the mathematically minimum number of transfers.

The application reuses `get_balances()` and then calls `suggest_settlements()`.
`GET /api/v1/groups/{group_id}/settlement-suggestions` includes member IDs, display
names, currency, and amounts; unknown groups return 404 and settled groups return
an empty suggestions list. Suggestions have no storage model; confirmation below
creates a Settlement only after revalidating a current suggestion.

## Recording actual payments

`POST /api/v1/groups/{group_id}/settlements` records a transfer that already
occurred outside TripTab; TripTab does not move money. The application constructs
the existing immutable `Settlement`, and the repository validates group membership
before flushing it in the application-owned transaction. The transaction commits
once. The recording actor is the authenticated User. Failures roll back
the payment; the existing authenticated account is retained. No balance columns
are stored.

The sender's balance increases by the amount; the recipient's decreases. For
Alice `+600`, Bob `-300`, and Charlie `-300`, recording Bob paying Alice NT$300
yields Alice `+300`, Bob `0`, and Charlie `-300`. A NT$100 partial payment leaves
Bob owing NT$200. A NT$400 payment makes Bob's balance `+100`: overpayments remain
valid actual history, and can reverse who owes whom. Neither the current balance
nor a suggested amount caps an actual payment.

`GET /api/v1/groups/{group_id}/settlements` returns actual recorded payments with
display names, ordered by `occurred_at` descending, then UUID descending (matching
expense-history ordering). Payment history stays separate from expense history.
Suggestions are never included in it.

## Confirming a current suggestion (M17C)

These are distinct commands:

| POST path under `/api/v1/groups/{group_id}` | Body | Meaning |
| --- | --- | --- |
| `/settlements` | Sender/recipient UUIDs, amount, aware `occurred_at` | Record an arbitrary real external transfer; partial payments and overpayments remain valid |
| `/settlement-suggestions/confirm` | `from_member_id`, `to_member_id`, positive integer NTD `amount` | Confirm one exact **current** derived suggestion; the server records the UTC confirmation time |

Confirmation runs in one application-owned transaction: authorize Trip access,
lock the Trip financial mutations, authorize the existing owner/linked sender/linked
recipient rule, reload effective expenses/splits/settlements, derive balances and
suggestions with the unchanged pure accounting functions, and find an exact
sender/recipient/amount match. Only a current match becomes a new immutable
Settlement. Nothing is persisted for the suggestion itself.

A successful confirmation returns 201 with the existing Settlement response.
A missing exact match returns the existing structured 409 conflict and rolls back
without inserting a Settlement. Authentication, CSRF, Origin and no-store policies
remain unchanged; 401/403/404/422 follow the existing authenticated creation
conventions. Missing or cross-Trip members remain 404. A generic Settlement never
passes through suggestion matching and remains valid even if it differs from any
suggestion.

All seven financial commands acquire the same Group row `FOR NO KEY UPDATE` lock
before reading effective financial state or mutating financial child rows, and hold
it until commit/rollback. The six existing commands are Expense create/correct/void
and Settlement create/correct/void. With PostgreSQL's default READ COMMITTED,
queries after a waiting lock see the preceding writer's committed state. Thus two
clients confirming Bob → Alice NT$300 against a single current suggestion yield
one success and one conflict, one Settlement and zero final balances. Other expense
or transfer changes serialize with this same revalidation point.

The shared wrapper is `_financial_transaction(group_id)`; repository writes still
flush but never commit. The lock is compatible with Group foreign-key key-share
locks, avoiding an inversion with invitation/member workflows that lock a member
first. Financial commands acquire the Group lock before child-row locks. See
[the PostgreSQL row-lock conflict matrix](https://www.postgresql.org/docs/18/explicit-locking.html).

The Balances UI shows personal and traveler net positions, then **Suggested
transfers**. **Mark settled** opens a native modal with explicit external-transfer
wording; **Confirm settled** submits the exact API tuple, never an amount computed
by the browser. Cancel creates nothing. Success refreshes balances, suggestions
and payment history. A 409 refreshes and asks the user to review; it never retries
automatically. Current payment correction/void controls remain in History, linked
by **View settlement history**; the generic manual creation UI is deferred.

This is atomic current-suggestion validation, not a generic idempotency guarantee:
a new legitimate financial state might later derive the same tuple. An uncertain
network/5xx response blocks resubmission from that dialog and directs the user to
history before trying again. No idempotency table, persisted suggestion, ledger
version, migration or second accounting formula is introduced.

The authenticated current User supplies `created_by_user_id` for expense and
settlement creation, voids, and corrections. Group authorization lives in the
application layer; see [the permission rules](authentication.md). Accounting
remains pure and does not inspect login sessions or membership roles.

## Voids, corrections, and effective history

Financial history is immutable after entry: **void is not delete**, and
**correction is not update**. There are no financial PATCH or DELETE endpoints.
A void inserts an `ExpenseVoid` or `SettlementVoid` with the original ID, reason,
UTC recording time, and actor. The original financial fields and expense splits
remain stored. A correction saves a new complete Expense (Equal or Exact) or
Settlement and its original's void record in one application-owned transaction.
The new record has its own UUID and recording time. A failure rolls back the new
record, its splits, and the void together; the authenticated account remains.

Full audit history includes all original and replacement records. Effective
financial history contains only records without a corresponding void. The
repository selects this effective history **before** the existing pure
`calculate_balances()` function runs; neither accounting nor domain imports ORM
void rows. Suggestions reuse these same derived balances. No second balance
formula or stored balance is introduced.

For an Equal expense paid by Alice for Alice, Bob, and Charlie, correcting 900 to
990 changes balances from `+600/-300/-300` to `+660/-330/-330`. Voiding that expense
without replacement makes its contribution zero. Correcting Bob's payment to
Alice from 300 to 200 uses only the 200 payment; voiding it restores the balances
before that payment. Other active financial records continue to contribute.

Correction chains keep immediate links: A corrected by B, then B corrected by C,
leaves A and B voided and C active. Voiding C does not reactivate A or B. The void
row's optional `replacement_id` supplies both `replaced_by_id` on the original
and `replaces_id` on the replacement. No original financial row is updated to
maintain links. Existing list responses retain full history and add `status`,
`void_reason`, `void_created_at`, `void_created_by_user_id`, `replaces_id`, and
`replaced_by_id`. Expense detail returns this metadata too. IDs are nonrecursive.

The frontend's **Current expenses** and **Current payments** lists contain only
active records. Voided records and previous versions remain in a collapsed
**Show expense/payment history** section, with reasons, recorded/void timestamps,
and links showing the amounts of immediate earlier/later versions. A current
replacement's **View edit history** link opens that section and reveals its
previous version. History is read-only; normal current records need no Active badge.

Active records offer **Edit** and an accessible trash-can **Delete expense/payment**
action. Edit starts with the original values and saves through the existing
correction endpoint: a complete replacement and the original's void are committed
atomically. Delete asks for confirmation and a reason, then uses the existing void
endpoint; it never deletes financial rows. Both explain that the previous record
stays in history. Every successful change refreshes expenses, payments, balances,
and suggestions from the API. Retrieval still returns full audit history; only
its presentation is separated. The frontend does no balance arithmetic.

All six creation/void/correction operations use the authenticated User as actor.
Original history keeps its original actor ID even when corrected by an owner.

## Collaborative account claiming

Claiming a Guest links an account to the existing GroupMember UUID. It changes no
expense, split, settlement, void/replacement reference or accounting input identity.
Balances and suggestions immediately before/after claiming are identical. The
newly linked account uses normal Member permissions; its later records carry its
User as recording actor independently of which traveler paid. See [invitations](invitations.md).
