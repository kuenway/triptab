import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { AuthProvider } from "../components/auth";
import { TripShell } from "../components/trip-shell";
import { TripSection } from "../components/trip-dashboard";
import { api, ApiError, Traveler } from "../lib/api";

vi.mock("next/navigation", () => ({ usePathname: () => "/trips/trip/balances", useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("next/link", () => ({ default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a> }));
vi.mock("../lib/api", async original => { const client = await original<typeof import("../lib/api")>(); return { ...client, api: Object.fromEntries(Object.keys(client.api).map(key => [key, vi.fn()])) }; });
const trip = { id: "trip", name: "Japan 2027", currency: "TWD" as const, currency_scale: 0 as const };
const members: Traveler[] = [
  { id: "alice", group_id: trip.id, display_name: "Alice", user_id: "alice-account", role: "owner" },
  { id: "bob", group_id: trip.id, display_name: "Bob", user_id: "bob-account", role: "member" },
  { id: "charlie", group_id: trip.id, display_name: "Charlie", user_id: "charlie-account", role: "member" },
];
const suggestion = { from_member_id: "bob", from_display_name: "Bob", to_member_id: "alice", to_display_name: "Alice", amount: 123456 };
const suggestions = { group_id: trip.id, currency: "TWD" as const, suggestions: [suggestion] };
const values = (a: number, b: number, c = 0) => ({ group_id: trip.id, currency: "TWD" as const, balances: members.map((m, i) => ({ member_id: m.id, display_name: m.display_name, amount: [a, b, c][i]! })) });
function balances() { return render(<AuthProvider><TripShell tripId={trip.id}><TripSection section="balances" /></TripShell></AuthProvider>); }
async function open() { const trigger = await screen.findByRole("button", { name: /^Mark settled/ }); trigger.focus(); fireEvent.click(trigger); return within(screen.getByRole("dialog", { name: "Mark this transfer as settled?" })); }
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.getMe).mockResolvedValue({ user: { id: "alice-account", email: "alice@example.com", display_name: "Account name differs", created_at: "2026-10-11T00:00:00Z" }, csrf_token: "test-csrf" });
  vi.mocked(api.getTrip).mockResolvedValue(trip); vi.mocked(api.listTravelers).mockResolvedValue(members); vi.mocked(api.listExpenses).mockResolvedValue([]); vi.mocked(api.listSettlements).mockResolvedValue([]);
  vi.mocked(api.getBalances).mockResolvedValue(values(123456, -123456)); vi.mocked(api.getSettlementSuggestions).mockResolvedValue(suggestions);
});

it.each([[123456, "You are owed"], [-123456, "You owe"], [0, "You're settled up"]] as const)("shows authoritative personal balance %i with textual meaning", async (amount, label) => {
  vi.mocked(api.getBalances).mockResolvedValue(values(amount, -amount)); balances(); expect(await screen.findByText(label)).toBeTruthy();
  const region = within(screen.getByRole("region", { name: "Balances" })); expect(region.getByText("You")).toBeTruthy(); expect(region.getByText("Charlie")).toBeTruthy(); expect(region.getAllByText("Settled").length).toBeGreaterThan(0);
  if (amount) expect(region.getAllByText(/NT\$123,456/).length).toBeGreaterThan(0);
  expect(screen.queryByRole("heading", { name: "Record payment" })).toBeNull(); expect(screen.queryByLabelText("Payment amount (NT$)")).toBeNull();
  expect(screen.getByRole("link", { name: "View settlement history" })).toHaveProperty("href", "http://localhost:3000/trips/trip/history");
});
it("does not call everyone settled just because the signed-in traveler is zero", async () => {
  vi.mocked(api.getBalances).mockResolvedValue(values(0, 500, -500)); vi.mocked(api.getSettlementSuggestions).mockResolvedValue({ ...suggestions, suggestions: [] }); balances(); await screen.findByText("You're settled up"); expect(screen.queryByText("Everyone is settled up.")).toBeNull(); expect(screen.getByText("Is owed NT$500")).toBeTruthy(); expect(screen.getByText("Owes NT$500")).toBeTruthy();
});
it("shows everyone settled only with nonempty loaded zero balances and no suggestions", async () => {
  vi.mocked(api.getBalances).mockResolvedValue(values(0, 0)); vi.mocked(api.getSettlementSuggestions).mockResolvedValue({ ...suggestions, suggestions: [] }); balances(); expect(await screen.findByText("Everyone is settled up.")).toBeTruthy();
});
it.each(["no balances", "nonzero", "suggestions", "suggestions failure"])("avoids all-settled when authoritative data says %s", async state => {
  vi.mocked(api.getBalances).mockResolvedValue(state === "no balances" ? { ...values(0, 0), balances: [] } : state === "nonzero" ? values(100, -100) : values(0, 0));
  if (state === "suggestions failure") vi.mocked(api.getSettlementSuggestions).mockRejectedValue(new ApiError("Could not load transfers.", 503));
  else if (state !== "suggestions") vi.mocked(api.getSettlementSuggestions).mockResolvedValue({ ...suggestions, suggestions: [] });
  balances(); await screen.findByRole("heading", { name: "Balances" }); expect(screen.queryByText("Everyone is settled up.")).toBeNull();
});
it("does not resolve personal balance by a matching display name", async () => {
  vi.mocked(api.listTravelers).mockResolvedValue(members.map(m => ({ ...m, user_id: m.id === "bob" ? "alice-account" : null, display_name: m.id === "alice" ? "Account name differs" : m.display_name })));
  balances(); expect(await screen.findByText("You owe")).toBeTruthy(); expect(screen.getByRole("heading", { name: "You to Alice" })).toBeTruthy(); expect(screen.getByRole("button", { name: /Mark settled: You to Alice/ })).toBeTruthy();
});
it("shows intentional loading with no zero or settled fallback", async () => {
  vi.mocked(api.getBalances).mockReturnValue(new Promise(() => {})); balances(); expect(await screen.findByText("Loading trip…")).toBeTruthy(); expect(screen.queryByText("Everyone is settled up.")).toBeNull(); expect(screen.queryByText("You're settled up")).toBeNull();
});
it("keeps balance failure retryable without fabricated balances", async () => {
  vi.mocked(api.getBalances).mockRejectedValueOnce(new ApiError("Balances unavailable.", 503)).mockResolvedValue(values(123456, -123456)); balances(); expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Balances unavailable."); expect(screen.queryByText("Everyone is settled up.")).toBeNull(); fireEvent.click(screen.getByRole("button", { name: "Try again" })); expect(await screen.findByText("You are owed")).toBeTruthy();
});
it("suggestion failure preserves readable balances and can retry independently", async () => {
  vi.mocked(api.getSettlementSuggestions).mockRejectedValueOnce(new ApiError("Transfers unavailable.", 503)).mockResolvedValue(suggestions); balances(); expect(await screen.findByText("You are owed")).toBeTruthy(); expect(screen.getByRole("alert")).toHaveProperty("textContent", "Transfers unavailable."); expect(screen.queryByRole("button", { name: /^Mark settled/ })).toBeNull(); fireEvent.click(screen.getByRole("button", { name: "Retry suggestions" })); expect(await screen.findByRole("button", { name: /^Mark settled/ })).toBeTruthy();
});
it.each([["bob-account", true], ["charlie-account", false]] as const)("only shows authorized transfer actions to %s", async (userId, permitted) => {
  vi.mocked(api.getMe).mockResolvedValue({ user: { id: userId, email: "member@example.com", display_name: "Alice", created_at: "2026-10-11T00:00:00Z" }, csrf_token: "test-csrf" }); balances(); await screen.findByRole("heading", { name: "Suggested transfers" }); expect(Boolean(screen.queryByRole("button", { name: /^Mark settled/ }))).toBe(permitted);
});
it("cancel and Escape create nothing and restore the transfer trigger", async () => {
  balances(); const dialog = await open(); expect(document.activeElement).toBe(dialog.getByRole("button", { name: "Cancel" })); fireEvent.click(dialog.getByRole("button", { name: "Cancel" })); expect(screen.queryByRole("dialog")).toBeNull(); expect(document.activeElement).toBe(screen.getByRole("button", { name: /^Mark settled/ }));
  await open(); fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true })); expect(screen.queryByRole("dialog")).toBeNull(); expect(api.confirmSettlementSuggestion).not.toHaveBeenCalled(); expect(api.recordSettlement).not.toHaveBeenCalled();
});
it("saves only the exact suggestion through the dedicated API then refreshes", async () => {
  vi.mocked(api.confirmSettlementSuggestion).mockResolvedValue({} as Awaited<ReturnType<typeof api.confirmSettlementSuggestion>>); vi.mocked(api.getBalances).mockResolvedValueOnce(values(123456, -123456)).mockResolvedValue(values(0, 0)); vi.mocked(api.getSettlementSuggestions).mockResolvedValueOnce(suggestions).mockResolvedValue({ ...suggestions, suggestions: [] }); balances(); const dialog = await open(); expect(dialog.getByText(/outside TripTab/)).toBeTruthy(); expect(dialog.getByText(/updates Trip balances/)).toBeTruthy(); fireEvent.click(dialog.getByRole("button", { name: "Confirm settled" }));
  expect(await screen.findByText("Settlement confirmed.")).toBeTruthy(); expect(screen.queryByRole("dialog")).toBeNull(); expect(api.confirmSettlementSuggestion).toHaveBeenCalledExactlyOnceWith(trip.id, { from_member_id: "bob", to_member_id: "alice", amount: 123456 }); expect(api.recordSettlement).not.toHaveBeenCalled(); expect(api.getBalances).toHaveBeenCalledTimes(2); expect(api.getSettlementSuggestions).toHaveBeenCalledTimes(2); expect(screen.getByText("Everyone is settled up.")).toBeTruthy();
});
it("409 refreshes state, explains the stale suggestion and never retries automatically", async () => {
  vi.mocked(api.confirmSettlementSuggestion).mockRejectedValue(new ApiError("settlement suggestion has changed", 409)); vi.mocked(api.getBalances).mockResolvedValueOnce(values(123456, -123456)).mockResolvedValue(values(0, 0)); vi.mocked(api.getSettlementSuggestions).mockResolvedValueOnce(suggestions).mockResolvedValue({ ...suggestions, suggestions: [] }); balances(); const dialog = await open(); fireEvent.click(dialog.getByRole("button", { name: "Confirm settled" })); expect(await screen.findByText(/This settlement suggestion has changed/)).toBeTruthy(); expect(api.getBalances).toHaveBeenCalledTimes(2); expect(api.getSettlementSuggestions).toHaveBeenCalledTimes(2); expect(api.confirmSettlementSuggestion).toHaveBeenCalledTimes(1); expect(api.recordSettlement).not.toHaveBeenCalled(); expect(screen.queryByRole("dialog")).toBeNull();
});
it("a safe 403 keeps confirmation open without reporting success", async () => {
  vi.mocked(api.confirmSettlementSuggestion).mockRejectedValue(new ApiError("only sender, recipient, or group owner may record a payment", 403)); balances(); const dialog = await open(); fireEvent.click(dialog.getByRole("button", { name: "Confirm settled" })); expect(await dialog.findByRole("alert")).toHaveProperty("textContent", "only sender, recipient, or group owner may record a payment"); expect(screen.queryByText("Settlement confirmed.")).toBeNull();
});
it.each([0, 503])("uncertain response %i blocks resubmission and points to history", async status => {
  vi.mocked(api.confirmSettlementSuggestion).mockRejectedValue(new ApiError("Unavailable", status)); balances(); const dialog = await open(); fireEvent.click(dialog.getByRole("button", { name: "Confirm settled" })); expect(await dialog.findByRole("alert")).toHaveProperty("textContent", "Could not confirm whether the settlement was saved. Close this dialog and check settlement history before trying again."); expect(dialog.getByRole("button", { name: "Confirm settled" })).toHaveProperty("disabled", true); fireEvent.click(dialog.getByRole("button", { name: "Confirm settled" })); expect(api.confirmSettlementSuggestion).toHaveBeenCalledTimes(1);
});
it("does not allow closing while confirmation is pending", async () => {
  let done!: () => void; vi.mocked(api.confirmSettlementSuggestion).mockReturnValue(new Promise(resolve => { done = () => resolve({} as Awaited<ReturnType<typeof api.confirmSettlementSuggestion>>); })); balances(); const dialog = await open(); fireEvent.click(dialog.getByRole("button", { name: "Confirm settled" })); expect(dialog.getByRole("button", { name: "Cancel" })).toHaveProperty("disabled", true); fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true })); expect(screen.getByRole("dialog")).toBeTruthy(); done(); await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});


it("wraps forward and backward keyboard focus within confirmation", async () => {
  balances(); const dialog = await open(); const cancel = dialog.getByRole("button", { name: "Cancel" }), confirm = dialog.getByRole("button", { name: "Confirm settled" });
  confirm.focus(); fireEvent.keyDown(confirm, { key: "Tab" }); expect(document.activeElement).toBe(cancel);
  fireEvent.keyDown(cancel, { key: "Tab", shiftKey: true }); expect(document.activeElement).toBe(confirm);
});
