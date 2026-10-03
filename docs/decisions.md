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
