import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { FinancialTimeline, historyEvents } from "../components/financial-timeline";
import { Expense, Settlement, Traveler } from "../lib/api";

vi.mock("../components/auth", () => ({ useAuth: () => ({ user: { id: "alice-user", display_name: "Account name" } }) }));
const travelers: Traveler[] = [
  { id: "alice", group_id: "trip", display_name: "Alice", user_id: "alice-user", role: "owner" },
  { id: "bob", group_id: "trip", display_name: "Bob", user_id: null, role: "member" },
  { id: "editor", group_id: "trip", display_name: "Charlie", user_id: "charlie-user", role: "member" },
];
const stamp = (days: number, hour: number) => { const date = new Date(); date.setDate(date.getDate() + days); date.setHours(hour, 0, 0, 0); return date.toISOString(); };
const expense: Expense = { id: "expense", group_id: "trip", description: "Lunch", amount: 800, payer_member_id: "bob", split_strategy: "equal", splits: [{ member_id: "alice", amount: 400 }, { member_id: "bob", amount: 400 }], occurred_at: "2026-01-01T09:00:00Z", created_at: stamp(-1, 10), created_by_user_id: "charlie-user", status: "active" };
const payment: Settlement = { id: "settlement", group_id: "trip", from_member_id: "bob", to_member_id: "alice", from_display_name: "Bob", to_display_name: "Alice", amount: 620, occurred_at: expense.occurred_at, created_at: stamp(0, 12), created_by_user_id: "charlie-user", status: "active" };
const onChanged = vi.fn().mockResolvedValue(undefined);
function timeline(expenses: Expense[] = [], payments: Settlement[] | null = [], error = "") { return render(<FinancialTimeline expenses={expenses} payments={payments} travelers={travelers} tripId="trip" error={error} onChanged={onChanged} />); }
beforeEach(() => vi.clearAllMocks());

it("reconstructs only proven correction/removal events, ordered by mutation time rather than external dates", () => {
  const first = { ...expense, status: "voided" as const, replaced_by_id: "replacement", void_created_at: stamp(0, 10), void_created_by_user_id: "alice-user", void_reason: "Receipt amount" };
  const edited = { ...expense, id: "replacement", amount: 920, created_at: stamp(0, 10), created_by_user_id: "alice-user", replaces_id: expense.id, status: "voided" as const, void_created_at: stamp(0, 11), void_created_by_user_id: "charlie-user", void_reason: "Duplicate" };
  const oldPayment = { ...payment, status: "voided" as const, replaced_by_id: "new-settlement", void_created_at: stamp(0, 13), void_reason: "Actual amount" };
  const newPayment = { ...payment, id: "new-settlement", amount: 500, replaces_id: payment.id, created_at: stamp(0, 13), status: "voided" as const, void_created_at: stamp(0, 14), void_created_by_user_id: "alice-user", void_reason: "Never transferred" };
  const events = historyEvents([edited, first], [newPayment, oldPayment]);
  expect(events.map(e => `${e.kind}:${e.action}`)).toEqual(["settlement:removed", "settlement:edited", "settlement:added", "expense:removed", "expense:edited", "expense:added"]);
  timeline([edited, first], [newPayment, oldPayment]);
  expect(screen.getAllByRole("heading", { level: 4 }).map(h => h.textContent)).toEqual(["Settlement removed", "Settlement corrected", "Bob settled with You", "Lunch removed", "Lunch edited", "Lunch added"]);
  expect(screen.getByRole("heading", { name: "Today" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Yesterday" })).toBeTruthy();
  const edit = screen.getByRole("heading", { name: "Lunch edited" }).closest("article")!;
  expect(edit.textContent).toContain("NT$800"); expect(edit.textContent).toContain("NT$920");
  expect(within(edit).getByText("Edited by You")).toBeTruthy();
  fireEvent.click(within(edit).getByText("Details", { exact: false })); expect(within(edit).getByText("Reason: Receipt amount")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  expect(screen.queryByText("Voided", { exact: true })).toBeNull();
});
it("keeps actor separate from payer and transfer participants and resolves You exclusively by IDs", () => {
  timeline([expense], [payment]);
  const added = screen.getByRole("heading", { name: "Lunch added" }).closest("article")!;
  expect(within(added).getByText("Recorded by Charlie")).toBeTruthy(); expect(within(added).getByText(/Bob paid/)).toBeTruthy();
  const settled = screen.getByRole("heading", { name: "Bob settled with You" }).closest("article")!;
  expect(within(settled).getByText("Recorded by Charlie")).toBeTruthy();
  expect(within(settled).queryByText("Recorded by Bob")).toBeNull();
});
it("uses neutral event copy for unavailable historical actors rather than the payer, sender or current user", () => {
  timeline([{ ...expense, created_by_user_id: "unknown-user", status: "voided", void_created_at: stamp(0, 10), void_created_by_user_id: null }], [{ ...payment, created_by_user_id: "unknown-user" }]);
  expect(screen.getByRole("heading", { name: "Lunch removed" })).toBeTruthy();
  expect(screen.queryByText(/Recorded by|Removed by/)).toBeNull();
});
it("does not fabricate removal timestamps or correction-before values when unavailable", () => {
  const records = [{ ...expense, replaces_id: "not-in-response", status: "voided" as const }];
  expect(historyEvents(records, [])).toHaveLength(1);timeline(records);
  expect(screen.getByRole("heading", { name: "Lunch edited" })).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "Lunch removed" })).toBeNull();
});
it("summarizes description, payer and split changes using stored values", () => {
  timeline([expense, { ...expense, id: "updated", replaces_id: expense.id, description: "Dinner", payer_member_id: "alice", splits: [{ member_id: "bob", amount: 800 }], created_at: stamp(0, 10) }]);
  expect(screen.getByText("Description: Lunch → Dinner")).toBeTruthy();
  expect(screen.getByText("Paid by: Bob → You")).toBeTruthy();
  expect(screen.getByText("Split allocations changed")).toBeTruthy();
});
it("renders an empty state only after both financial collections loaded", () => {
  const view = timeline();expect(screen.getByRole("heading", { name: "No history yet." })).toBeTruthy();
  view.rerender(<FinancialTimeline expenses={[]} payments={null} travelers={travelers} tripId="trip" error="" onChanged={onChanged} />);
  expect(screen.getByRole("status").textContent).toBe("Loading history…");expect(screen.queryByText("No history yet.")).toBeNull();
});
it("keeps read failures distinct from empty history and offers Retry", () => {
  timeline([expense], null, "Could not refresh settlements.");expect(screen.getByRole("alert").textContent).toBe("Could not refresh settlements.");expect(screen.queryByText("No history yet.")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Retry history" }));expect(onChanged).toHaveBeenCalledOnce();
});
it("keeps authorized active settlement controls secondary inside a keyboard-native disclosure", () => {
  timeline([], [payment]);const details = screen.getByText("Details", { exact: false }).closest("details")!;expect(details.open).toBe(false);
  fireEvent.click(details.querySelector("summary")!);expect(within(details).getByRole("button", { name: "Edit" })).toBeTruthy();expect(within(details).getByRole("button", { name: "Delete payment" })).toBeTruthy();
  fireEvent.click(within(details).getByRole("button", { name: "Edit" }));expect(screen.getByRole("group", { name: "Edit payment" })).toBeTruthy();
});
