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
