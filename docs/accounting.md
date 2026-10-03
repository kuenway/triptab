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
Inactive-member selection, void/replacement filtering, persistence, idempotency,
concurrency controls, and settlement suggestions are deferred.
