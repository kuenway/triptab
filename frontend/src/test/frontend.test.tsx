import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import Home from "../app/page";
import { BalanceList, ExpenseForm, ExpenseHistory, TravelerForm, TripDashboard } from "../components/trip-dashboard";
import { PaymentForm, PaymentHistory, SuggestedPayments } from "../components/payments";
import { api, ApiError, Expense, Settlement, SettlementSuggestions, Traveler, Trip } from "../lib/api";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a> }));
vi.mock("../lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../lib/api")>();
  return {
    ...original,
    api: Object.fromEntries(Object.keys(original.api).map((key) => [key, vi.fn()])),
  };
});

const trip: Trip = { id: "trip-1", name: "Tokyo Weekend", currency: "TWD", currency_scale: 0 };
const travelers: Traveler[] = [
  { id: "alice", group_id: trip.id, display_name: "Alice", user_id: null },
  { id: "bob", group_id: trip.id, display_name: "Bob", user_id: null },
  { id: "charlie", group_id: trip.id, display_name: "Charlie", user_id: null },
];
const expense: Expense = {
  id: "expense-1", group_id: trip.id, description: "Dinner", amount: 900,
  payer_member_id: "alice", split_strategy: "equal",
  splits: travelers.map((traveler) => ({ member_id: traveler.id, amount: 300 })),
  occurred_at: "2026-10-03T10:00:00Z", created_at: "2026-10-03T11:00:00Z",
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.getSettlementSuggestions).mockResolvedValue({ group_id: trip.id, currency: "TWD", suggestions: [] });
  vi.mocked(api.listSettlements).mockResolvedValue([]);
});

it("renders trips from the API", async () => {
  vi.mocked(api.listTrips).mockResolvedValue([trip]);
  render(<Home />);
  expect(await screen.findByRole("link", { name: /Tokyo Weekend/ })).toHaveProperty("href", "http://localhost:3000/trips/trip-1");
});

it("shows the empty trip state", async () => {
  vi.mocked(api.listTrips).mockResolvedValue([]);
  render(<Home />);
  expect(await screen.findByText("No trips yet")).toBeTruthy();
});

it("creates a trip and navigates to it", async () => {
  vi.mocked(api.listTrips).mockResolvedValue([]);
  vi.mocked(api.createTrip).mockResolvedValue(trip);
  render(<Home />);
  fireEvent.change(screen.getByLabelText("Trip name"), { target: { value: "Tokyo Weekend" } });
  fireEvent.click(screen.getByRole("button", { name: "Create trip" }));
  await waitFor(() => expect(api.createTrip).toHaveBeenCalledWith("Tokyo Weekend"));
  await waitFor(() => expect(push).toHaveBeenCalledWith("/trips/trip-1"));
});

it("shows a create-trip API error beside the form", async () => {
  vi.mocked(api.listTrips).mockResolvedValue([]);
  vi.mocked(api.createTrip).mockRejectedValue(new ApiError("Trip could not be saved.", 422));
  render(<Home />);
  fireEvent.change(screen.getByLabelText("Trip name"), { target: { value: "Tokyo Weekend" } });
  fireEvent.click(screen.getByRole("button", { name: "Create trip" }));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Trip could not be saved.");
});

it("adds a traveler and reports API errors", async () => {
  const onAdded = vi.fn();
  vi.mocked(api.addTraveler).mockResolvedValueOnce(travelers[0]).mockRejectedValueOnce(new ApiError("Traveler could not be saved.", 422));
  render(<TravelerForm tripId={trip.id} onAdded={onAdded} />);
  fireEvent.change(screen.getByLabelText("Traveler name"), { target: { value: "Alice" } });
  fireEvent.click(screen.getByRole("button", { name: "Add traveler" }));
  await waitFor(() => expect(onAdded).toHaveBeenCalledOnce());
  fireEvent.change(screen.getByLabelText("Traveler name"), { target: { value: "Bob" } });
  fireEvent.click(screen.getByRole("button", { name: "Add traveler" }));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Traveler could not be saved.");
});

function fillExpense() {
  fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Dinner" } });
  fireEvent.change(screen.getByLabelText("Amount (NT$)"), { target: { value: "900" } });
  fireEvent.change(screen.getByLabelText("When did it happen?"), { target: { value: "2026-10-03T10:00" } });
}

it("submits Equal participants without forcing the payer into the split", async () => {
  vi.mocked(api.addExpense).mockResolvedValue(expense);
  render(<ExpenseForm tripId={trip.id} travelers={travelers} onCreated={vi.fn()} />);
  fillExpense();
  fireEvent.click(screen.getByLabelText("Bob", { selector: "input[type=checkbox]" }));
  fireEvent.click(screen.getByLabelText("Charlie", { selector: "input[type=checkbox]" }));
  fireEvent.click(screen.getByRole("button", { name: "Add expense" }));
  await waitFor(() => expect(api.addExpense).toHaveBeenCalledWith(trip.id, expect.objectContaining({
    payer_member_id: "alice", split_strategy: "equal", participant_member_ids: ["bob", "charlie"], amount: 900,
  })));
  expect(await screen.findByText(/Stored split:/)).toBeTruthy();
});

it("shows Exact allocation totals and blocks a mismatch", async () => {
  vi.mocked(api.addExpense).mockResolvedValue(expense);
  render(<ExpenseForm tripId={trip.id} travelers={travelers} onCreated={vi.fn()} />);
  fillExpense();
  fireEvent.click(screen.getByLabelText("Exact amounts"));
  fireEvent.click(screen.getByLabelText("Alice", { selector: "input[type=checkbox]" }));
  fireEvent.click(screen.getByLabelText("Bob", { selector: "input[type=checkbox]" }));
  fireEvent.change(screen.getByLabelText("Alice allocation"), { target: { value: "500" } });
  fireEvent.change(screen.getByLabelText("Bob allocation"), { target: { value: "300" } });
  expect(screen.getByText("Allocated NT$800 of NT$900")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Add expense" }).hasAttribute("disabled")).toBe(true);
  fireEvent.change(screen.getByLabelText("Bob allocation"), { target: { value: "400" } });
  expect(screen.getByRole("button", { name: "Add expense" }).hasAttribute("disabled")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Add expense" }));
  await waitFor(() => expect(api.addExpense).toHaveBeenCalledWith(trip.id, expect.objectContaining({
    split_strategy: "exact", splits: [{ member_id: "alice", amount: 500 }, { member_id: "bob", amount: 400 }],
  })));
});

it("renders backend balance signs and stored expense allocations", () => {
  render(<>
    <BalanceList balances={{ group_id: trip.id, currency: "TWD", balances: [
      { member_id: "alice", display_name: "Alice", amount: 600 },
      { member_id: "bob", display_name: "Bob", amount: -300 },
      { member_id: "charlie", display_name: "Charlie", amount: 0 },
    ] }} />
    <ExpenseHistory expenses={[expense]} travelers={travelers} />
  </>);
  expect(screen.getByText("gets back NT$600")).toBeTruthy();
  expect(screen.getByText("owes NT$300")).toBeTruthy();
  expect(screen.getByText("settled")).toBeTruthy();
  expect(screen.getByText("Alice NT$300")).toBeTruthy();
});

it("shows a missing trip without exposing an API exception", async () => {
  vi.mocked(api.getTrip).mockRejectedValue(new ApiError("group not found", 404));
  vi.mocked(api.listTravelers).mockResolvedValue([]);
  vi.mocked(api.listExpenses).mockResolvedValue([]);
  vi.mocked(api.getBalances).mockResolvedValue({ group_id: trip.id, currency: "TWD", balances: [] });
  render(<TripDashboard tripId="unknown" />);
  expect(await screen.findByText("We couldn’t find that trip.")).toBeTruthy();
});

const suggestions: SettlementSuggestions = {
  group_id: trip.id,
  currency: "TWD",
  suggestions: [
    { from_member_id: "bob", from_display_name: "Bob", to_member_id: "alice", to_display_name: "Alice", amount: 1234 },
    { from_member_id: "charlie", from_display_name: "Charlie", to_member_id: "alice", to_display_name: "Alice", amount: 300 },
  ],
};

it.each([1, 2])("renders %i suggested payments with names and whole TWD amounts", (count) => {
  render(<SuggestedPayments tripId={trip.id} travelers={travelers} onRecorded={vi.fn().mockResolvedValue(undefined)} suggestions={{ ...suggestions, suggestions: suggestions.suggestions.slice(0, count) }} />);
  expect(screen.getByText("Bob → Alice")).toBeTruthy();
  expect(screen.getByText("NT$1,234")).toBeTruthy();
  if (count === 2) {
    expect(screen.getByText("Charlie → Alice")).toBeTruthy();
    expect(screen.getByText("NT$300")).toBeTruthy();
  }
  expect(screen.getAllByRole("button", { name: "Mark as paid" })).toHaveLength(count);
  expect(screen.queryByRole("checkbox")).toBeNull();
});

it("shows the settled suggestion empty state", () => {
  render(<SuggestedPayments tripId={trip.id} travelers={travelers} onRecorded={vi.fn().mockResolvedValue(undefined)} suggestions={{ ...suggestions, suggestions: [] }} />);
  expect(screen.getByText("Everyone is settled up.")).toBeTruthy();
});

function mockDashboard() {
  vi.mocked(api.getTrip).mockResolvedValue(trip);
  vi.mocked(api.listTravelers).mockResolvedValue(travelers);
  vi.mocked(api.listExpenses).mockResolvedValue([expense]);
  vi.mocked(api.getBalances).mockResolvedValue({ group_id: trip.id, currency: "TWD", balances: [] });
}

it("loads backend suggestions into the trip with explicit payment actions", async () => {
  mockDashboard();
  vi.mocked(api.getSettlementSuggestions).mockResolvedValue(suggestions);
  render(<TripDashboard tripId={trip.id} />);
  expect(await screen.findByText("Bob → Alice")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Suggested payments" })).toBeTruthy();
  expect(screen.getByText("Mark as paid only after a payment happened outside TripTab.")).toBeTruthy();
  expect(api.getSettlementSuggestions).toHaveBeenCalledWith(trip.id);
  expect(screen.getAllByRole("button", { name: "Mark as paid" })).toHaveLength(2);
});

it("shows suggestion API errors without claiming everyone is settled", async () => {
  mockDashboard();
  vi.mocked(api.getSettlementSuggestions).mockRejectedValue(new ApiError("Could not load suggested payments.", 500));
  render(<TripDashboard tripId={trip.id} />);
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Could not load suggested payments.");
  expect(screen.getByRole("heading", { name: "Suggested payments" })).toBeTruthy();
  expect(screen.queryByText("Everyone is settled up.")).toBeNull();
});

it("refreshes suggestions from the backend after an expense is saved", async () => {
  mockDashboard();
  vi.mocked(api.getSettlementSuggestions).mockResolvedValueOnce(suggestions).mockResolvedValueOnce({ ...suggestions, suggestions: [] });
  vi.mocked(api.addExpense).mockResolvedValue(expense);
  render(<TripDashboard tripId={trip.id} />);
  expect(await screen.findByText("Bob → Alice")).toBeTruthy();
  fillExpense();
  fireEvent.click(screen.getByLabelText("Bob", { selector: "input[type=checkbox]" }));
  fireEvent.click(screen.getByRole("button", { name: "Add expense" }));
  expect(await screen.findByText("Everyone is settled up.")).toBeTruthy();
  expect(api.getSettlementSuggestions).toHaveBeenCalledTimes(2);
  expect(screen.queryByText("Bob → Alice")).toBeNull();
});

const payment: Settlement = {
  id: "payment-1", group_id: trip.id,
  from_member_id: "bob", from_display_name: "Bob",
  to_member_id: "alice", to_display_name: "Alice", amount: 300,
  occurred_at: "2026-10-03T12:30:00Z", created_at: "2026-10-03T12:31:00Z",
};

it("requires explicit confirmation and supports cancelling a suggested payment", () => {
  render(<SuggestedPayments tripId={trip.id} travelers={travelers} suggestions={suggestions} onRecorded={vi.fn().mockResolvedValue(undefined)} />);
  fireEvent.click(screen.getAllByRole("button", { name: "Mark as paid" })[0]);
  const confirmation = screen.getByRole("group", { name: "Record payment?" });
  expect(within(confirmation).getByText(/This records that Bob paid Alice NT\$1,234 outside TripTab/)).toBeTruthy();
  expect(within(confirmation).getByText("TripTab does not transfer money.")).toBeTruthy();
  expect(api.recordSettlement).not.toHaveBeenCalled();
  fireEvent.click(within(confirmation).getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("group", { name: "Record payment?" })).toBeNull();
  expect(api.recordSettlement).not.toHaveBeenCalled();
});

it("records a suggestion once while pending and waits for the authoritative refresh", async () => {
  let resolvePayment!: (value: Settlement) => void;
  vi.mocked(api.recordSettlement).mockReturnValue(new Promise((resolve) => { resolvePayment = resolve; }));
  const onRecorded = vi.fn().mockResolvedValue(undefined);
  render(<SuggestedPayments tripId={trip.id} travelers={travelers} suggestions={suggestions} onRecorded={onRecorded} />);
  fireEvent.click(screen.getAllByRole("button", { name: "Mark as paid" })[0]);
  const confirmation = screen.getByRole("group", { name: "Record payment?" });
  fireEvent.change(within(confirmation).getByLabelText("When did the payment happen?"), { target: { value: "2026-10-03T12:30" } });
  const form = within(confirmation).getByRole("button", { name: "Record payment" }).closest("form")!;
  fireEvent.submit(form);
  fireEvent.submit(form);
  expect(api.recordSettlement).toHaveBeenCalledTimes(1);
  expect(api.recordSettlement).toHaveBeenCalledWith(trip.id, {
    from_member_id: "bob", to_member_id: "alice", amount: 1234,
    occurred_at: new Date("2026-10-03T12:30").toISOString(),
  });
  expect(within(confirmation).getByRole("button", { name: "Recording…" }).hasAttribute("disabled")).toBe(true);
  expect(onRecorded).not.toHaveBeenCalled();
  resolvePayment(payment);
  await waitFor(() => expect(onRecorded).toHaveBeenCalledOnce());
  await waitFor(() => expect(screen.queryByRole("group", { name: "Record payment?" })).toBeNull());
});

function fillPayment(amount = "100") {
  fireEvent.change(screen.getByLabelText("From traveler"), { target: { value: "bob" } });
  fireEvent.change(screen.getByLabelText("To traveler"), { target: { value: "alice" } });
  fireEvent.change(screen.getByLabelText("Payment amount (NT$)"), { target: { value: amount } });
  fireEvent.change(screen.getByLabelText("When did the payment happen?"), { target: { value: "2026-10-03T12:30" } });
}

it.each(["100", "400"])("records a manual custom payment of %s NTD", async (amount) => {
  vi.mocked(api.recordSettlement).mockResolvedValue({ ...payment, amount: Number(amount) });
  const onRecorded = vi.fn().mockResolvedValue(undefined);
  render(<PaymentForm tripId={trip.id} travelers={travelers} onRecorded={onRecorded} />);
  fillPayment(amount);
  fireEvent.click(screen.getByRole("button", { name: "Record payment" }));
  await waitFor(() => expect(api.recordSettlement).toHaveBeenCalledWith(trip.id, expect.objectContaining({ from_member_id: "bob", to_member_id: "alice", amount: Number(amount) })));
  expect(await screen.findByText("Payment recorded.")).toBeTruthy();
  await waitFor(() => expect(onRecorded).toHaveBeenCalledOnce());
});

it("rejects the same sender and recipient without making a write", () => {
  render(<PaymentForm tripId={trip.id} travelers={travelers} onRecorded={vi.fn().mockResolvedValue(undefined)} />);
  fillPayment();
  fireEvent.change(screen.getByLabelText("To traveler"), { target: { value: "bob" } });
  fireEvent.click(screen.getByRole("button", { name: "Record payment" }));
  expect(screen.getByRole("alert")).toHaveProperty("textContent", "Sender and recipient must be different travelers.");
  expect(api.recordSettlement).not.toHaveBeenCalled();
});

it.each(["0", "1.5"])("rejects invalid manual amounts (%s)", (amount) => {
  render(<PaymentForm tripId={trip.id} travelers={travelers} onRecorded={vi.fn().mockResolvedValue(undefined)} />);
  fillPayment(amount);
  fireEvent.submit(screen.getByRole("button", { name: "Record payment" }).closest("form")!);
  expect(screen.getByRole("alert")).toHaveProperty("textContent", "Enter a positive whole NTD amount.");
  expect(api.recordSettlement).not.toHaveBeenCalled();
});

it.each([
  [new ApiError("Payment could not be recorded.", 422), "Payment could not be recorded."],
  [new ApiError("Network failed.", 0), "Could not confirm whether the payment was recorded. Refresh payment history before trying again."],
])("shows payment errors without implying a successful write", async (error, message) => {
  vi.mocked(api.recordSettlement).mockRejectedValue(error);
  const onRecorded = vi.fn().mockResolvedValue(undefined);
  render(<PaymentForm tripId={trip.id} travelers={travelers} onRecorded={onRecorded} />);
  fillPayment();
  fireEvent.click(screen.getByRole("button", { name: "Record payment" }));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", message);
  expect(screen.queryByText("Payment recorded.")).toBeNull();
  expect(onRecorded).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Record payment" }).hasAttribute("disabled")).toBe(false);
});

it("renders actual payment history with names, amounts and event dates", () => {
  render(<PaymentHistory payments={[payment]} />);
  expect(screen.getByRole("heading", { name: "Bob paid Alice" })).toBeTruthy();
  expect(screen.getByText("NT$300")).toBeTruthy();
  expect(screen.getByText(new Date(payment.occurred_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }))).toBeTruthy();
});

it("shows the empty payment history state", () => {
  render(<PaymentHistory payments={[]} />);
  expect(screen.getByText("No payments recorded yet.")).toBeTruthy();
});

it("refreshes backend balances, suggestions and history after confirming a payment", async () => {
  mockDashboard();
  vi.mocked(api.getBalances).mockResolvedValueOnce({ group_id: trip.id, currency: "TWD", balances: [] }).mockResolvedValueOnce({ group_id: trip.id, currency: "TWD", balances: [
    { member_id: "alice", display_name: "Alice", amount: 300 },
    { member_id: "bob", display_name: "Bob", amount: 0 },
    { member_id: "charlie", display_name: "Charlie", amount: -300 },
  ] });
  const initial = { ...suggestions, suggestions: suggestions.suggestions.map((value) => ({ ...value, amount: 300 })) };
  vi.mocked(api.getSettlementSuggestions).mockResolvedValueOnce(initial).mockResolvedValueOnce({ ...initial, suggestions: [initial.suggestions[1]] });
  vi.mocked(api.listSettlements).mockResolvedValueOnce([]).mockResolvedValueOnce([payment]);
  vi.mocked(api.recordSettlement).mockResolvedValue(payment);
  render(<TripDashboard tripId={trip.id} />);
  await screen.findByText("Bob → Alice");
  fireEvent.click(screen.getAllByRole("button", { name: "Mark as paid" })[0]);
  fireEvent.click(within(screen.getByRole("group", { name: "Record payment?" })).getByRole("button", { name: "Record payment" }));
  expect(await screen.findByRole("heading", { name: "Bob paid Alice" })).toBeTruthy();
  expect(screen.getByText("gets back NT$300")).toBeTruthy();
  expect(screen.getByText("settled")).toBeTruthy();
  expect(screen.getByText("owes NT$300")).toBeTruthy();
  expect(screen.queryByText("Bob → Alice")).toBeNull();
  expect(screen.getByText("Charlie → Alice")).toBeTruthy();
  expect(api.getBalances).toHaveBeenCalledTimes(2);
  expect(api.getSettlementSuggestions).toHaveBeenCalledTimes(2);
  expect(api.listSettlements).toHaveBeenCalledTimes(2);
});

it("shows payment history read errors without presenting an empty history", async () => {
  mockDashboard();
  vi.mocked(api.listSettlements).mockRejectedValue(new ApiError("Could not load payment history.", 500));
  render(<TripDashboard tripId={trip.id} />);
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Could not load payment history.");
  expect(screen.queryByText("No payments recorded yet.")).toBeNull();
});
