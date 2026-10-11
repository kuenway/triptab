import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AuthProvider } from "../components/auth";
import { TripShell } from "../components/trip-shell";
import { TripSection } from "../components/trip-dashboard";
import { api, ApiError, Expense, Traveler } from "../lib/api";

vi.mock("next/navigation", () => ({ usePathname: () => "/trips/trip", useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("next/link", () => ({ default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a> }));
vi.mock("../lib/api", async (original) => { const client = await original<typeof import("../lib/api")>(); return { ...client, api: Object.fromEntries(Object.keys(client.api).map(key => [key, vi.fn()])) }; });
const trip = { id: "trip", name: "Japan 2027", currency: "TWD" as const, currency_scale: 0 as const };
const travelers: Traveler[] = [
  { id: "alice", group_id: trip.id, user_id: "alice-user", display_name: "Alice", role: "owner" },
  { id: "bob", group_id: trip.id, user_id: null, display_name: "Bob", role: "member" },
  { id: "charlie", group_id: trip.id, user_id: null, display_name: "Charlie", role: "member" },
];
const expense: Expense = { id: "dinner", group_id: trip.id, created_by_user_id: "alice-user", description: "Dinner", amount: 100, payer_member_id: "alice", split_strategy: "equal", status: "active", splits: [{ member_id: "alice", amount: 34 }, { member_id: "bob", amount: 33 }, { member_id: "charlie", amount: 33 }], occurred_at: "2026-10-11T12:00:00Z", created_at: "2026-10-11T12:01:00Z" };
function ledger() { return render(<AuthProvider><TripShell tripId={trip.id}><TripSection section="expenses" /></TripShell></AuthProvider>); }
async function open() { fireEvent.click(await screen.findByRole("button", { name: "Add expense" })); return within(screen.getByRole("dialog", { name: "Add expense" })); }
function fill(form: ReturnType<typeof within>) { fireEvent.change(form.getByLabelText("Description"), { target: { value: "Lunch" } }); fireEvent.change(form.getByLabelText("Amount (NT$)"), { target: { value: "100" } }); }
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.getMe).mockResolvedValue({ user: { id: "alice-user", display_name: "Different account name", email: "alice@example.com", created_at: expense.created_at }, csrf_token: "csrf-test" });
  vi.mocked(api.getTrip).mockResolvedValue(trip); vi.mocked(api.listTravelers).mockResolvedValue(travelers); vi.mocked(api.listExpenses).mockResolvedValue([expense]);
  vi.mocked(api.getBalances).mockResolvedValue({ group_id: trip.id, currency: "TWD", balances: [{ member_id: "alice", display_name: "Alice", amount: 66 }] });
  vi.mocked(api.getSettlementSuggestions).mockResolvedValue({ group_id: trip.id, currency: "TWD", suggestions: [] }); vi.mocked(api.listSettlements).mockResolvedValue([]);
});
afterEach(() => vi.restoreAllMocks());

it("makes the ledger primary with authoritative balance, UUID payer, stored remainder share, count and collapsed allocations", async () => {
  ledger(); await screen.findByRole("heading", { name: "Dinner" });
  expect(screen.queryByRole("dialog")).toBeNull(); expect(screen.queryByLabelText("Description")).toBeNull();
  expect(screen.getByText("You paid · 3 travelers")).toBeTruthy(); expect(screen.getByText("Your share NT$34")).toBeTruthy(); expect(screen.getByText("You are owed NT$66")).toBeTruthy();
  expect(screen.getByRole("link", { name: "View balances →" })).toHaveProperty("href", "http://localhost:3000/trips/trip/balances"); expect(screen.queryByText("Active")).toBeNull();
  const details = screen.getByText("Details", { exact: false }).closest("details")!; expect(details.open).toBe(false); fireEvent.click(details.querySelector("summary")!);
  expect(within(details).getByText("Bob")).toBeTruthy(); expect(within(details).getAllByText("NT$33")).toHaveLength(2);
});
it.each([[[], null], [[{ member_id: "alice", amount: 0 }], "Your share NT$0"]] as const)("distinguishes nonparticipation from explicitly stored zero", async (splits, label) => {
  vi.mocked(api.listExpenses).mockResolvedValue([{ ...expense, splits: [...splits], split_strategy: "exact" }]); ledger(); await screen.findByRole("heading", { name: "Dinner" }); expect(screen.queryByText(/Your share/)?.textContent ?? null).toBe(label);
});
it("never resolves You by matching names or counts all Trip travelers as participants", async () => {
  vi.mocked(api.listTravelers).mockResolvedValue(travelers.map(m => m.id === "bob" ? { ...m, display_name: "Different account name" } : m));
  vi.mocked(api.listExpenses).mockResolvedValue([{ ...expense, payer_member_id: "bob", splits: [{ member_id: "bob", amount: 100 }] }]); ledger(); expect(await screen.findByText("Different account name paid · 1 traveler")).toBeTruthy(); expect(screen.queryByText(/Your share/)).toBeNull();
});
it("groups Today, Yesterday and older dates with deterministic ordering and history-only previous versions", async () => {
  const today = new Date(); today.setHours(12, 0, 0, 0); const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1); const older = new Date(today); older.setDate(today.getDate() - 5);
  vi.mocked(api.listExpenses).mockResolvedValue([
    { ...expense, id: "old", description: "Older", occurred_at: older.toISOString() },
    { ...expense, id: "yesterday", description: "Yesterday meal", occurred_at: yesterday.toISOString() },
    { ...expense, id: "b", description: "Today B", occurred_at: today.toISOString() },
    { ...expense, id: "a", description: "Today A", occurred_at: today.toISOString() },
    { ...expense, id: "void", description: "Old corrected version", status: "voided" },
  ]); ledger(); await screen.findByRole("heading", { name: "Today" });
  const current = within(screen.getByRole("group", { name: "Current expenses" })); expect(current.getAllByRole("heading", { level: 4 }).map(h => h.textContent)).toEqual(["Today A", "Today B", "Yesterday meal", "Older"]);
  expect(current.getByRole("heading", { name: "Yesterday" })).toBeTruthy(); expect(current.queryByRole("heading", { name: "Old corrected version" })).toBeNull(); fireEvent.click(screen.getByText("Show expense history (1)")); expect(screen.getByRole("heading", { name: "Old corrected version" })).toBeTruthy();
});
it("opens a focused titled dialog with local time, fresh defaults, clean close and trigger focus return", async () => {
  const confirm = vi.spyOn(window, "confirm"); ledger(); const form = await open(); expect(document.activeElement).toBe(form.getByLabelText("Description")); expect(form.getByRole("radio", { name: "Equal" })).toHaveProperty("checked", true); expect(form.getAllByRole("checkbox").every(b => (b as HTMLInputElement).checked)).toBe(true); expect(form.getByLabelText("Paid by")).toHaveProperty("value", "alice"); expect((form.getByLabelText("When did it happen?") as HTMLInputElement).value).not.toBe(""); fireEvent.click(form.getByRole("button", { name: "Close expense dialog" })); expect(confirm).not.toHaveBeenCalled(); expect(screen.queryByRole("dialog")).toBeNull(); expect(document.activeElement).toBe(screen.getByRole("button", { name: "Add expense" }));
});
it.each(["close", "cancel", "escape"])("confirms dirty %s without losing input when declined", async (action) => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true); ledger(); const form = await open(); fill(form);
  const close = () => action === "escape" ? fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true })) : fireEvent.click(form.getByRole("button", { name: action === "close" ? "Close expense dialog" : "Cancel" }));
  close(); expect(confirm).toHaveBeenCalledWith("Discard this expense draft? Your changes will be lost."); expect(form.getByLabelText("Description")).toHaveProperty("value", "Lunch"); close(); expect(screen.queryByRole("dialog")).toBeNull(); const fresh = await open(); expect(fresh.getByLabelText("Description")).toHaveProperty("value", "");
});
it("saves Exact allocations then closes and resets to fresh Equal defaults", async () => {
  vi.mocked(api.listExpenses).mockResolvedValueOnce([]).mockResolvedValue([expense]); vi.mocked(api.addExpense).mockResolvedValue(expense); ledger(); const form = await open(); fill(form); fireEvent.click(form.getByRole("radio", { name: "Exact amounts" }));
  for (const [name, value] of [["Alice", "34"], ["Bob", "33"], ["Charlie", "33"]]) fireEvent.change(form.getByLabelText(name + " allocation"), { target: { value } }); fireEvent.click(form.getByRole("button", { name: "Add expense" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull()); expect(api.addExpense).toHaveBeenCalledWith(trip.id, expect.objectContaining({ split_strategy: "exact", splits: expense.splits })); expect(screen.getByRole("heading", { name: "Dinner" })).toBeTruthy(); const fresh = await open(); expect(fresh.getByLabelText("Description")).toHaveProperty("value", ""); expect(fresh.getByRole("radio", { name: "Equal" })).toHaveProperty("checked", true);
});
it.each([422, 0])("preserves failed input and associates safe error %s with fields", async status => {
  vi.mocked(api.addExpense).mockRejectedValue(new ApiError("Invalid expense", status)); ledger(); const form = await open(); fill(form); fireEvent.click(form.getByRole("button", { name: "Add expense" })); const alert = await form.findByRole("alert"); expect(alert.textContent).toContain(status === 0 ? "Could not confirm whether the expense was saved" : "Invalid expense"); expect(form.getByLabelText("Description")).toHaveProperty("value", "Lunch"); expect(form.getByLabelText("Description").getAttribute("aria-describedby")).toBe(alert.id);
});
it("does not discard a submitted draft while the request is pending", async () => {
  let done!: (e: Expense) => void; vi.mocked(api.addExpense).mockReturnValue(new Promise(resolve => { done = resolve; })); ledger(); const form = await open(); fill(form); fireEvent.click(form.getByRole("button", { name: "Add expense" })); expect(form.getByRole("button", { name: "Close expense dialog" })).toHaveProperty("disabled", true); fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true })); expect(screen.getByRole("dialog")).toBeTruthy(); done(expense); await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});
it("reuses prefilled correction form and replaces current record without rewriting history", async () => {
  const replacement = { ...expense, id: "new", description: "Receipt dinner", amount: 120, replaces_id: expense.id }; const original = { ...expense, status: "voided" as const, replaced_by_id: replacement.id }; vi.mocked(api.listExpenses).mockResolvedValueOnce([expense]).mockResolvedValue([replacement, original]); vi.mocked(api.correctExpense).mockResolvedValue(replacement); ledger(); fireEvent.click(await screen.findByRole("button", { name: "Edit" })); const form = within(screen.getByRole("dialog", { name: "Edit expense" })); expect(form.getByLabelText("Amount (NT$)")).toHaveProperty("value", "100"); fireEvent.change(form.getByLabelText("Description"), { target: { value: "Receipt dinner" } }); fireEvent.change(form.getByLabelText("Amount (NT$)"), { target: { value: "120" } }); fireEvent.change(form.getByLabelText("Reason"), { target: { value: "Receipt" } }); fireEvent.click(form.getByRole("button", { name: "Save changes" })); await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull()); const current = within(screen.getByRole("group", { name: "Current expenses" })); expect(current.getByRole("heading", { name: "Receipt dinner" })).toBeTruthy(); expect(current.queryByRole("heading", { name: "Dinner" })).toBeNull(); fireEvent.click(current.getByRole("link", { name: "View edit history" })); expect(screen.getByRole("link", { name: "Replaced by another expense · NT$120" })).toBeTruthy();
});
it("keeps failed reads retryable without showing an empty or settled ledger", async () => {
  vi.mocked(api.listExpenses).mockRejectedValueOnce(new ApiError("Could not load expenses.", 503)).mockResolvedValue([expense]); ledger(); expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Could not load expenses."); expect(screen.queryByText("No expenses yet.")).toBeNull(); expect(screen.queryByText("You are settled up")).toBeNull(); fireEvent.click(screen.getByRole("button", { name: "Try again" })); expect(await screen.findByRole("heading", { name: "Dinner" })).toBeTruthy();
});
