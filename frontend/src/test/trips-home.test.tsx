import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import Home from "../app/page";
import { AuthProvider } from "../components/auth";
import { api, ApiError, Trip } from "../lib/api";
const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a> }));
vi.mock("../lib/api", async (original) => {
  const originalApi = await original<typeof import("../lib/api")>();
  return { ...originalApi, api: Object.fromEntries(Object.keys(originalApi.api).map(key => [key, vi.fn()])) };
});
const trip: Trip = { id: "trip-1", name: "Japan 2027", currency: "TWD", currency_scale: 0 };
function home() { return render(<AuthProvider><Home /></AuthProvider>); }
async function open() { fireEvent.click(await screen.findByRole("button", { name: "+ New trip" })); return screen.getByRole("dialog", { name: "New trip" }); }
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.getMe).mockResolvedValue({ user: { id: "alice", display_name: "Alice", email: "alice@example.com", created_at: "2026-10-11T12:00:00Z" }, csrf_token: "test-csrf" });
  vi.mocked(api.listTrips).mockResolvedValue([]);
});
it("renders name-only destinations with one list read and no per-Trip reads", async () => {
  const long = "A very long trip name ".repeat(8).trim();
  vi.mocked(api.listTrips).mockResolvedValue([trip, { ...trip, id: "trip-2", name: long }]); home();
  const list = await screen.findByRole("list", { name: "Your trips" });
  expect(within(list).getAllByRole("link")).toHaveLength(2);
  expect(within(list).getByRole("link", { name: long }).getAttribute("href")).toBe("/trips/trip-2");
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Your trips");
  expect(list.textContent).not.toMatch(/Updated|tripmates|TWD|Group|trip-1/);
  expect(api.listTrips).toHaveBeenCalledTimes(1); expect(api.getMe).toHaveBeenCalledTimes(1);
  for (const method of [api.getTrip, api.listTravelers, api.listExpenses, api.getBalances, api.listSettlements, api.getSettlementSuggestions]) expect(method).not.toHaveBeenCalled();
  expect(screen.queryByLabelText("Trip name")).toBeNull();
});
it("distinguishes authenticated loading from empty and auth states", async () => {
  vi.mocked(api.listTrips).mockReturnValue(new Promise(() => {})); home();
  expect(await screen.findByRole("status")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Your trips" })).toBeTruthy();
  expect(screen.queryByText("No trips yet.")).toBeNull(); expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();
});
it("shows a read error with Retry instead of an empty state", async () => {
  vi.mocked(api.listTrips).mockRejectedValueOnce(new ApiError("Read failed", 503)).mockResolvedValueOnce([trip]); home();
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Could not load your trips. Please retry.");
  expect(screen.queryByText("No trips yet.")).toBeNull(); fireEvent.click(screen.getByRole("button", { name: "Retry trips" }));
  expect(await screen.findByRole("link", { name: trip.name })).toBeTruthy();
  expect(api.listTrips).toHaveBeenCalledTimes(2); expect(api.getMe).toHaveBeenCalledTimes(1);
});
it("opens a named minimal dialog and restores focus after pristine close", async () => {
  home(); const trigger = await screen.findByRole("button", { name: "+ New trip" }); trigger.focus(); fireEvent.click(trigger);
  const dialog = screen.getByRole("dialog", { name: "New trip" }); expect(dialog.getAttribute("aria-describedby")).toBeTruthy();
  expect(document.activeElement).toBe(screen.getByLabelText("Trip name")); fireEvent(dialog, new Event("cancel", { cancelable: true }));
  expect(screen.queryByRole("dialog")).toBeNull(); expect(document.activeElement).toBe(trigger); expect(api.createTrip).not.toHaveBeenCalled();
});
it("preserves validation input, associates errors, and separates list failures", async () => {
  vi.mocked(api.listTrips).mockRejectedValue(new ApiError("Read failed", 503)); vi.mocked(api.createTrip).mockRejectedValue(new ApiError("Name rejected", 422)); home(); await open();
  const input = screen.getByLabelText("Trip name"); fireEvent.change(input, { target: { value: "   " } }); fireEvent.submit(input.closest("form")!);
  expect(screen.getByText("Enter a trip name.")).toBeTruthy(); expect(api.createTrip).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: trip.name } }); fireEvent.submit(input.closest("form")!);
  expect(await screen.findByText("Name rejected")).toBeTruthy(); expect(input).toHaveProperty("value", trip.name); expect(input.getAttribute("aria-invalid")).toBe("true");
  expect(document.getElementById(input.getAttribute("aria-describedby")!)?.textContent).toBe("Name rejected");
  expect(screen.getByText("Could not load your trips. Please retry.")).toBeTruthy(); expect(screen.getByRole("dialog")).toBeTruthy();
});
it("serializes create submission and stays locked until navigation resolves", async () => {
  let resolve!: (value: Trip) => void; vi.mocked(api.createTrip).mockReturnValue(new Promise(done => { resolve = done; })); home(); await open();
  const input = screen.getByLabelText("Trip name"); fireEvent.change(input, { target: { value: " Japan 2027 " } });
  fireEvent.submit(input.closest("form")!); fireEvent.submit(input.closest("form")!); expect(api.createTrip).toHaveBeenCalledTimes(1);
  fireEvent(screen.getByRole("dialog"), new Event("cancel", { cancelable: true })); expect(screen.getByRole("dialog")).toBeTruthy();
  resolve(trip); await waitFor(() => expect(push).toHaveBeenCalledWith("/trips/trip-1")); fireEvent.submit(input.closest("form")!);
  expect(api.createTrip).toHaveBeenCalledTimes(1); expect(api.createTrip).toHaveBeenCalledWith("Japan 2027");
});
it("checks uncertain creates without automatically resubmitting", async () => {
  vi.mocked(api.createTrip).mockRejectedValue(new ApiError("Network failure", 0)); home(); await open();
  const input = screen.getByLabelText("Trip name"); fireEvent.change(input, { target: { value: trip.name } }); fireEvent.submit(input.closest("form")!);
  expect(await screen.findByText(/Could not confirm whether the trip was created/)).toBeTruthy(); expect(input).toHaveProperty("value", trip.name);
  expect(screen.queryByRole("button", { name: "Create trip" })).toBeNull(); fireEvent.submit(input.closest("form")!); expect(api.createTrip).toHaveBeenCalledTimes(1);
  vi.mocked(api.listTrips).mockResolvedValue([trip]); fireEvent.click(screen.getByRole("button", { name: "Check your trips" }));
  expect(await screen.findByRole("link", { name: trip.name })).toBeTruthy(); expect(screen.queryByRole("dialog")).toBeNull(); expect(api.listTrips).toHaveBeenCalledTimes(2);
});

it("discloses account identity only in the home menu and restores focus on dismissal", async () => {
  home(); const trigger = await screen.findByRole("button", { name: "Account menu" });
  expect(trigger.textContent).toBe("A"); expect(trigger.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByText("alice@example.com")).toBeNull(); expect(screen.queryByText("Log out")).toBeNull();
  fireEvent.click(trigger);
  const account = screen.getByRole("group", { name: "Your account" });
  expect(within(account).getByText("alice@example.com")).toBeTruthy();
  expect(document.activeElement).toBe(within(account).getByRole("button", { name: "Sign out" }));
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("group", { name: "Your account" })).toBeNull(); expect(document.activeElement).toBe(trigger);
  fireEvent.click(trigger); fireEvent.click(screen.getByRole("heading", { name: "Your trips" }));
  expect(screen.queryByRole("group", { name: "Your account" })).toBeNull(); expect(document.activeElement).toBe(trigger);
  fireEvent.click(trigger); fireEvent.click(trigger); expect(screen.queryByText("alice@example.com")).toBeNull();
});
it("retains the account menu and current session when existing sign-out fails", async () => {
  vi.mocked(api.logout).mockRejectedValue(new ApiError("Could not sign out. Please retry.", 503)); home();
  fireEvent.click(await screen.findByRole("button", { name: "Account menu" }));
  fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Could not sign out. Please retry.");
  expect(screen.getByText("alice@example.com")).toBeTruthy(); expect(screen.getByRole("heading", { name: "Your trips" })).toBeTruthy();
  expect(api.logout).toHaveBeenCalledOnce();
});
