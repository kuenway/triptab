import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import Home from "../app/page";
import { BalanceList, ExpenseForm, ExpenseHistory, TravelerForm, TripDashboard } from "../components/trip-dashboard";
import { api, ApiError, Expense, Traveler, Trip } from "../lib/api";

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
