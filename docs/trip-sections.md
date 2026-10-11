# Trip sections and financial activity (M17D)

The persistent `/trips/[tripId]/layout.tsx` owns the authentication boundary and
TripShell. The root AuthProvider resolves the session once. TripShell is keyed
only by Trip ID: section navigation retains the header, navigation, session and
already-loaded Trip data; entering a different Trip resets the shell. Initial
session resolution and signed-out/direct links still use the M15 auth shell.

The previous `[tripId]/loading.tsx` introduced a section fallback during an
uncached route transition. Removing it lets Next.js transitions keep the previous
section until the destination is ready. The four real navigation Links explicitly
use native `prefetch={true}` for these small dynamic routes. Prefetch loads route
payloads, not additional ledger/session API data. `aria-current` follows the
committed pathname. The private-history developer footer was removed. This
baseline did not contain literal `Loading session` text; no auth-provider remount
or repeated-session-fetch workaround was added.

## Tripmates

Tripmates is product vocabulary only. `/travelers`, Traveler types, GroupMember
UUIDs, API fields/routes and database names remain unchanged. Quiet rows prioritize
identity and status, with Owner first and `You` derived from a linked User ID.
Owners manage invitations and may remove unused Guests through existing APIs.
Linked Members/Owners have no unsupported removal action. Pending links retain
New link/Revoke and replacement confirmation. Removal labels name the target.

Invitation metadata is owner-only. While it loads or fails, the UI does not label
an unknown status as No invitation or offer a misleading replacement action.
Errors offer Retry within the section; per-person action errors remain keyed by
member UUID. Add tripmate stays below the list, retains backend duplicate-name
validation, and displays its error beside the form. The client translates the
legacy traveler word in API error copy without changing HTTP status or contracts.

## Financial History

A single chronological financial activity list replaces the separate raw expense
and payment lists. No additional API, persisted event model, or financial mutation
is introduced. Current Expenses and derived Balances retain their existing
semantics. Invitations are not synthesized into financial activity.

| Event | Evidence | Ordering timestamp | Actor identity |
| --- | --- | --- | --- |
| Expense added / external settlement recorded | Original immutable record | `created_at` | `created_by_user_id` |
| Expense edited / Settlement corrected | `replaces_id` and predecessor values | Replacement `created_at` | Replacement `created_by_user_id` |
| Expense / Settlement removed | Voided record without a replacement | `void_created_at` | `void_created_by_user_id` |

A predecessor void linked to a replacement represents one edit, not an additional
removal event. Missing removal timestamps do not generate invented dated events.
A known replacement with an unavailable predecessor retains neutral edited copy
without fabricating before-values. Events sort newest first by timestamp and group
by the viewer's local calendar date (Today, Yesterday or a readable date), using
the same date-label helper as Expenses. External `occurred_at` is disclosed in
Details rather than used to order application activity. Equal timestamp events
retain response order; UUIDs do not establish chronology.

Actors resolve only from recorded User IDs: current User -> You, or an explicitly
account-linked GroupMember -> its current display name. Financial payer/sender/
recipient fields never establish actors. Unknown/unmapped historical actors have
neutral event copy with no invented Recorded by label. Names are current display
names, not historical name snapshots; new persisted snapshots/actor fields are
outside M17D. Financial `You` resolves independently through the authenticated
User's linked GroupMember UUID, never a name comparison.

The default timeline uses added/edited/removed and settled language, shows stored
amount changes, and summarizes payer/description/split/transfer-participant changes.
Native Details disclose occurrence dates, allocations, correction reasons and
preserved versions. Authorized active Settlement correction/removal remains
secondary inside Details; expense editing stays in the current Expenses ledger.
Loading, read errors and empty history are distinct; failed reads offer Retry and
never masquerade as empty history.

## Design review

Reviewed against the existing TripTab CSS tokens and component conventions; no
separate Figma/Storybook specification was supplied. Mobile (375px) and desktop
(1280px) browser captures/checks cover compact person rows, readable status text,
quiet actions, long-name/description wrapping, date groups and stored amounts.
Native disclosures keep the default timeline compact and keyboard accessible.
Navigation retains semantic links, visible focus, `aria-current` and 44px+ touch
targets. End-of-content scrolling verifies clearance above the fixed bottom nav.
DOM mutation observers and API request counts verify persistent shell nodes and
absence of auth/section/footer flashes during normal section navigation.

Frictions addressed: misleading invitation status during failed reads, generic
remove labels, a route fallback/footer flash and record-centric history wording.
No new fonts, icons, dependencies, animation framework, actor persistence, social
activity feed or M17E work was introduced. Production release remains a separate
review/push/CI/release step.
