# Domain validation boundary

The Python objects in `backend/app/domain/` validate facts available within one
object. Services introduced in later milestones will validate facts that require
other group members, other records, or the full ledger. The objects do not query a
database.

| Entity-local checks (Milestone 1) | Contextual or accounting checks (later) |
| --- | --- |
| IDs have UUID shape and required text is nonblank | A referenced user, group, or member actually exists |
| Group currency is TWD with scale 0 | Members and transactions belong to the same group |
| Expense amount is a positive integer NTD value | An expense has at least one valid participant |
| Split amount is a nonnegative integer NTD value | Split member IDs are unique and allocations total the expense amount |
| Expense strategy is Equal or Exact | Exact inputs total the requested amount; Equal allocations use the approved rounding rule |
| Settlement amount is positive and sender differs from recipient | Settlement members belong to the group; balances reflect the transfer |
| `occurred_at` and `created_at` are timezone-aware | The application sets trustworthy `created_at` and actor values |

An `Expense` carries final allocation records but does not calculate or certify
them. Its payer is a separate member ID from the split participant IDs; the payer
may be absent from the splits. `occurred_at` describes the real-world event, while
`created_at` records when the application entered it. Neither object generates a
timestamp or requires those two times to be equal.

There is no stored balance on `User` or `GroupMember`. The accounting milestone
will derive balances from valid financial history. Financial corrections will use
void and replacement records in a later milestone.
