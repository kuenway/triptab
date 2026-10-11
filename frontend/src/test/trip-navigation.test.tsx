import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { AnchorHTMLAttributes, ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import TripLayout from "../app/trips/[tripId]/layout";
import ExpensesPage from "../app/trips/[tripId]/page";
import BalancesPage from "../app/trips/[tripId]/balances/page";
import TravelersPage from "../app/trips/[tripId]/travelers/page";
import HistoryPage from "../app/trips/[tripId]/history/page";
import { AuthProvider } from "../components/auth";
import { api, ApiError, Trip } from "../lib/api";

const navigation = vi.hoisted(() => ({ pathname: "/trips/trip", tripId: "trip", push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useParams: () => ({ tripId: navigation.tripId }),
  useRouter: () => navigation,
}));
vi.mock("next/link", () => ({ default: ({ children, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>) => <a {...props}>{children}</a> }));
vi.mock("../lib/api", async (original) => {
  const client = await original<typeof import("../lib/api")>();
  return { ...client, api: Object.fromEntries(Object.keys(client.api).map((key) => [key, vi.fn()])) };
});

const trip: Trip = { id: "trip", name: "Japan 2027", currency: "TWD", currency_scale: 0 };
const auth = { user: { id: "alice-user", display_name: "Alice", email: "alice@example.com", created_at: "2026-10-11T12:00:00Z" }, csrf_token: "csrf-test" };
function route(page: ReactNode) { return <AuthProvider><TripLayout>{page}</TripLayout></AuthProvider>; }

beforeEach(() => {
  vi.resetAllMocks();
  navigation.pathname = "/trips/trip"; navigation.tripId = "trip";
  vi.mocked(api.getMe).mockResolvedValue(auth);
  vi.mocked(api.getTrip).mockResolvedValue(trip);
  vi.mocked(api.listTravelers).mockResolvedValue([{ id: "alice", group_id: trip.id, display_name: "Alice", user_id: auth.user.id, role: "owner" }]);
  vi.mocked(api.listExpenses).mockResolvedValue([]);
  vi.mocked(api.getBalances).mockResolvedValue({ group_id: trip.id, currency: "TWD", balances: [] });
  vi.mocked(api.getSettlementSuggestions).mockResolvedValue({ group_id: trip.id, currency: "TWD", suggestions: [] });
  vi.mocked(api.listSettlements).mockResolvedValue([]);
  vi.mocked(api.listInvitations).mockResolvedValue([]);
});

it.each([
  ["", "Expenses", ExpensesPage, ["Expenses"]],
  ["/balances", "Balances", BalancesPage, ["Balances", "Your balance", "Tripmate balances", "Suggested transfers"]],
  ["/travelers", "Tripmates", TravelersPage, ["Tripmates"]],
  ["/history", "History", HistoryPage, ["History", "No history yet."]],
] as const)("renders only the requested section at /trips/trip%s", async (suffix, active, Page, headings) => {
  navigation.pathname += suffix;
  render(route(<Page />));
  await screen.findByRole("heading", { name: trip.name });
  const nav = within(screen.getByRole("navigation", { name: "Trip sections" }));
  const links = nav.getAllByRole("link");
  expect(links).toHaveLength(4);
  expect(links.filter((link) => link.getAttribute("aria-current") === "page")).toEqual([nav.getByRole("link", { name: active })]);
  for (const [name, path] of [["Expenses", ""], ["Balances", "/balances"], ["Tripmates", "/travelers"], ["History", "/history"]]) {
    expect(nav.getByRole("link", { name })).toHaveProperty("href", "http://localhost:3000/trips/trip" + path);
  }
  expect(screen.queryByRole("tab")).toBeNull();
  for (const name of ["Expenses", "Add an expense", "Current expenses", "Balances", "Your balance", "Tripmate balances", "Suggested transfers", "Suggested payments", "Record payment", "Current payments", "Tripmates", "History", "No history yet.", "Expense history", "Payment history"]) {
    expect(screen.queryAllByRole("heading", { name })).toHaveLength(headings.some((heading) => heading === name) ? 1 : 0);
  }
  expect(screen.getAllByRole("main")).toHaveLength(1);
  expect(screen.getByText("1 tripmate · TWD")).toBeTruthy();
  if (active !== "Tripmates") expect(api.listInvitations).not.toHaveBeenCalled();
});

it("retains shared Trip data across section navigation without decorative requests", async () => {
  const view = render(route(<ExpensesPage />));
  await screen.findByRole("heading", { name: "Expenses" });
  navigation.pathname = "/trips/trip/balances";
  view.rerender(route(<BalancesPage />));
  expect(screen.getByRole("heading", { name: "Balances" })).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "Expenses" })).toBeNull();
  for (const request of [api.getTrip, api.listTravelers, api.listExpenses, api.getBalances, api.getSettlementSuggestions, api.listSettlements]) expect(request).toHaveBeenCalledOnce();
});

it("does not show Expenses while a directly opened Balances route is loading", async () => {
  let resolve!: (trip: Trip) => void;
  vi.mocked(api.getTrip).mockReturnValue(new Promise((done) => { resolve = done; }));
  navigation.pathname = "/trips/trip/balances";
  render(route(<BalancesPage />));
  await waitFor(() => expect(api.getTrip).toHaveBeenCalled());
  expect(screen.getByRole("status")).toHaveProperty("textContent", "Loading trip…");
  expect(screen.queryByRole("heading", { name: "Add an expense" })).toBeNull();
  resolve(trip);
  expect(await screen.findByRole("heading", { name: "Balances" })).toBeTruthy();
});

it("remounts the shell when the Trip ID changes, hiding the previous Trip during loading", async () => {
  const view = render(route(<TravelersPage />));
  await screen.findByRole("heading", { name: trip.name });
  let resolve!: (trip: Trip) => void;
  vi.mocked(api.getTrip).mockReturnValue(new Promise((done) => { resolve = done; }));
  navigation.tripId = "other"; navigation.pathname = "/trips/other/travelers";
  view.rerender(route(<TravelersPage />));
  await waitFor(() => expect(api.getTrip).toHaveBeenCalledWith("other"));
  expect(screen.queryByRole("heading", { name: trip.name })).toBeNull();
  resolve({ ...trip, id: "other", name: "Other Trip" });
  expect(await screen.findByRole("heading", { name: "Other Trip" })).toBeTruthy();
});

it("shows a Trip network error with retry without presenting a signed-out screen", async () => {
  vi.mocked(api.getTrip).mockRejectedValueOnce(new ApiError("Could not load Trip.", 0)).mockResolvedValue(trip);
  render(route(<BalancesPage />));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Could not load Trip.");
  expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();
  expect(navigation.replace).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByRole("heading", { name: "Balances" })).toBeTruthy();
});

it("keeps signed-out direct section URLs behind the existing auth shell", async () => {
  vi.mocked(api.getMe).mockRejectedValue(new ApiError("authentication required", 401));
  render(route(<HistoryPage />));
  await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/login"));
  expect(api.getTrip).not.toHaveBeenCalled();
  expect(screen.queryByRole("navigation")).toBeNull();
});

it("distinguishes an auth connectivity error from being signed out", async () => {
  vi.mocked(api.getMe).mockRejectedValue(new ApiError("network failure", 0));
  render(route(<TravelersPage />));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Could not check your sign-in. Please try again.");
  expect(navigation.replace).not.toHaveBeenCalled();
  expect(api.getTrip).not.toHaveBeenCalled();
});

it("does not expose inaccessible Trip content on a section URL", async () => {
  vi.mocked(api.getTrip).mockRejectedValue(new ApiError("group not found", 404));
  render(route(<HistoryPage />));
  expect(await screen.findByRole("heading", { name: "We couldn’t find that trip." })).toBeTruthy();
  expect(screen.queryByRole("navigation")).toBeNull();
  expect(screen.queryByRole("heading", { name: "History" })).toBeNull();
});


it("reuses immutable expense history and settlement controls on the History route", async () => {
  const expense = { id: "original", group_id: trip.id, description: "Dinner", amount: 900, payer_member_id: "alice", split_strategy: "equal" as const, splits: [{ member_id: "alice", amount: 900 }], occurred_at: "2026-10-11T12:00:00Z", created_at: "2026-10-11T12:01:00Z", created_by_user_id: auth.user.id, status: "voided" as const, void_reason: "Receipt correction", replaced_by_id: "replacement" };
  vi.mocked(api.listExpenses).mockResolvedValue([expense, { ...expense, id: "replacement", description: "Updated dinner", amount: 990, status: "active", replaces_id: expense.id, replaced_by_id: null }]);
  vi.mocked(api.listSettlements).mockResolvedValue([{ id: "payment", group_id: trip.id, from_member_id: "bob", to_member_id: "alice", from_display_name: "Bob", to_display_name: "Alice", amount: 300, occurred_at: expense.occurred_at, created_at: expense.created_at, created_by_user_id: auth.user.id, status: "active" }]);
  navigation.pathname = "/trips/trip/history";
  render(route(<HistoryPage />));
  expect(await screen.findByRole("heading", { name: "Updated dinner edited" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Dinner added" })).toBeTruthy();
  fireEvent.click(screen.getByRole("heading", { name: "Updated dinner edited" }).closest("article")!.querySelector("summary")!);
  expect(screen.getByText("Reason: Receipt correction")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Bob settled with You" })).toBeTruthy();
  fireEvent.click(screen.getByRole("heading", { name: "Bob settled with You" }).closest("article")!.querySelector("summary")!);
  expect(screen.getByRole("button", { name: "Edit" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Delete payment" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Delete expense" })).toBeNull();
});

it("keeps resolved auth and the same shell/header/nav through all four destinations", async () => {
  const view = render(route(<ExpensesPage />));
  const nav = await screen.findByRole("navigation", { name: "Trip sections" });
  const main = screen.getByRole("main");
  const header = main.querySelector("header");
  for (const [path, Page, heading] of [["balances", BalancesPage, "Balances"], ["travelers", TravelersPage, "Tripmates"], ["history", HistoryPage, "History"], ["", ExpensesPage, "Expenses"]] as const) {
    navigation.pathname = "/trips/trip" + (path ? "/" + path : "");
    view.rerender(route(<Page />));
    expect(screen.getByRole("navigation")).toBe(nav);
    expect(screen.getByRole("main")).toBe(main);
    expect(main.querySelector("header")).toBe(header);
    expect(screen.getByRole("heading", { name: heading })).toBeTruthy();
    expect(screen.queryByText(/Loading session|Private trip · Financial history/)).toBeNull();
    expect(main.querySelector(".auth-shell")).toBeNull();
  }
  expect(api.getMe).toHaveBeenCalledOnce();
  expect(api.getTrip).toHaveBeenCalledOnce();
});
