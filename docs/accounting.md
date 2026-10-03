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
Inactive-member selection, idempotency, ledger versions, and general concurrency
controls remain deferred. The application loads effective persisted history before
calling accounting; duplicate voids are protected by database uniqueness.

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
an empty suggestions list. Suggestions have no write endpoint or storage model.

## Recording actual payments

`POST /api/v1/groups/{group_id}/settlements` records a transfer that already
occurred outside TripTab; TripTab does not move money. The application constructs
the existing immutable `Settlement`, and the repository validates group membership
before flushing it in the application-owned transaction. The transaction commits
once, including creation of the development actor if needed. Failures roll back
both the payment and any newly created actor. No balance columns are stored.

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

A displayed suggestion can become stale. Confirming it asserts that the supplied
real-world transfer occurred, rather than executing a current financial plan.
There is no suggestion pointer or ledger-version check. After recording a payment,
the frontend refreshes authoritative balances, suggestions, and payment history;
it does not calculate balance changes itself.

The payment form disables submission while a request or refresh is pending and
guards repeated submissions from the same form interaction. This is UI protection,
not an exactly-once guarantee. An uncertain network response may follow a committed
write; check payment history before retrying. Server-side idempotency, ledger
versions, and optimistic locking remain production-hardening concerns.

The single internal `DEVELOPMENT_ACTOR` in `app/application/service.py` supplies
`created_by_user_id` for expense and settlement creation, voids, and corrections.
It is not an authenticated user and must be replaced by the real authenticated
actor in all six operations when authentication is added.

## Voids, corrections, and effective history

Financial history is immutable after entry: **void is not delete**, and
**correction is not update**. There are no financial PATCH or DELETE endpoints.
A void inserts an `ExpenseVoid` or `SettlementVoid` with the original ID, reason,
UTC recording time, and actor. The original financial fields and expense splits
remain stored. A correction saves a new complete Expense (Equal or Exact) or
Settlement and its original's void record in one application-owned transaction.
The new record has its own UUID and recording time. A failure rolls back the new
record, its splits, the void, and any new development actor together.

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

The frontend displays these statuses, reasons, and links in the existing expense
and payment histories. Active records offer Correct and Void. A correction form
starts with the original values and requires a reason and complete replacement;
a void asks for confirmation and a reason. Both explain that the original stays
in history. Every successful change refreshes expenses, payments, balances, and
suggestions from the API. The frontend does no balance arithmetic.

The same internal `DEVELOPMENT_ACTOR` records all six operations: expense creation,
settlement creation, expense void, expense correction, settlement void, and
settlement correction. Correction uses it for both replacement and void. Replace
all these recording uses with the authenticated actor when authentication arrives.
This actor does not confer access control. There is no authentication or
permission enforcement yet.
