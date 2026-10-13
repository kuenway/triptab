import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Home from "../app/page";
import { AuthForm, AuthProvider } from "../components/auth";
import { COLD_START_MESSAGE_DELAY_MS, LOADING_REVEAL_DELAY_MS, LoadingState } from "../components/loading-state";
import { api, ApiError, AuthState, Trip } from "../lib/api";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace }) }));
vi.mock("next/link", () => ({ default: ({ href, children, className }: { href: string; children: ReactNode; className?: string }) => <a href={href} className={className}>{children}</a> }));
vi.mock("../lib/api", async original => {
  const originalApi = await original<typeof import("../lib/api")>();
  return { ...originalApi, api: Object.fromEntries(Object.keys(originalApi.api).map(key => [key, vi.fn()])) };
});
const auth: AuthState = { user: { id: "alice", email: "alice@example.com", display_name: "Alice", created_at: "2026-10-12T12:00:00Z" }, csrf_token: "test-csrf" };
const trip: Trip = { id: "trip-1", name: "Japan 2027", currency: "TWD", currency_scale: 0 };
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: Error) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
async function home() { await act(async () => { render(<AuthProvider><Home /></AuthProvider>); }); }
async function advance(ms: number) { await act(async () => { vi.advanceTimersByTime(ms); }); }
beforeEach(() => {
  vi.resetAllMocks(); vi.useFakeTimers();
  vi.mocked(api.getMe).mockResolvedValue(auth);
  vi.mocked(api.listTrips).mockResolvedValue([trip]);
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

it("fast session and list responses render content immediately without revealing the traveler", async () => {
  await home();
  expect(screen.getByRole("link", { name: trip.name })).toBeTruthy();
  expect(document.querySelector(".loading-state")).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
  expect(api.getMe).toHaveBeenCalledOnce(); expect(api.listTrips).toHaveBeenCalledOnce();
});
it("does not flash a list animation when its response arrives before 250ms", async () => {
  const read = deferred<Trip[]>(); vi.mocked(api.listTrips).mockReturnValue(read.promise);
  await home(); await advance(LOADING_REVEAL_DELAY_MS - 1);
  expect(document.querySelector(".loading-revealed")).toBeNull();
  await act(async () => { read.resolve([trip]); });
  expect(screen.getByRole("link", { name: trip.name })).toBeTruthy();
  expect(document.querySelector(".loading-state")).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
});
it("unresolved auth remains neutral, reveals after 250ms and reports a cold start once", async () => {
  const session = deferred<AuthState>(); vi.mocked(api.getMe).mockReturnValue(session.promise);
  await home();
  expect(screen.getByRole("status").textContent).toBe("Getting things ready…");
  expect(screen.queryByRole("heading")).toBeNull(); expect(api.listTrips).not.toHaveBeenCalled();
  await advance(LOADING_REVEAL_DELAY_MS - 1); expect(document.querySelector(".loading-revealed")).toBeNull();
  await advance(1); expect(document.querySelector(".loading-session.loading-revealed")).not.toBeNull();
  expect(document.querySelector("svg.travel-loading-illustration")?.getAttribute("aria-hidden")).toBe("true");
  expect(document.querySelector("svg.travel-loading-illustration")?.getAttribute("focusable")).toBe("false");
  expect(document.querySelector(".skeleton-bar")).toBeNull();
  expect(screen.getByRole("status").getAttribute("aria-live")).toBe("polite");
  expect(document.querySelector(".loading-surface button, .loading-surface a, .loading-surface [tabindex]")).toBeNull();
  expect(screen.queryByText("Loading…")).toBeNull();
  await advance(COLD_START_MESSAGE_DELAY_MS - LOADING_REVEAL_DELAY_MS - 1);
  expect(screen.queryByText("Starting TripTab…")).toBeNull();
  await advance(1); expect(screen.getByRole("status").textContent).toBe("Starting TripTab…");
  await act(async () => { session.resolve(auth); });
  expect(screen.getByRole("link", { name: trip.name })).toBeTruthy();
  expect(screen.queryByRole("status")).toBeNull(); expect(vi.getTimerCount()).toBe(0);
});
it("authenticated list loading uses the same traveler without showing empty content", async () => {
  const read = deferred<Trip[]>(); vi.mocked(api.listTrips).mockReturnValue(read.promise);
  await home(); await advance(LOADING_REVEAL_DELAY_MS);
  expect(screen.getByRole("heading", { name: "Your trips" })).toBeTruthy();
  expect(screen.getByRole("status").textContent).toBe("Getting things ready…");
  expect(document.querySelectorAll(".travel-loading-illustration")).toHaveLength(1);
  expect(document.querySelector(".skeleton-bar")).toBeNull();
  expect(screen.queryByText("No trips yet.")).toBeNull(); expect(screen.queryByRole("list")).toBeNull();
  await advance(COLD_START_MESSAGE_DELAY_MS - LOADING_REVEAL_DELAY_MS);
  expect(screen.getByText("Starting TripTab…")).toBeTruthy();
  await act(async () => { read.resolve([]); });
  expect(screen.getByRole("heading", { name: "No trips yet." })).toBeTruthy();
  expect(screen.queryByRole("status")).toBeNull(); expect(vi.getTimerCount()).toBe(0);
});
it("a failed list exits cold-start loading and Retry uses the existing list request", async () => {
  const first = deferred<Trip[]>(), retry = deferred<Trip[]>();
  vi.mocked(api.listTrips).mockReturnValueOnce(first.promise).mockReturnValueOnce(retry.promise);
  await home(); await advance(COLD_START_MESSAGE_DELAY_MS);
  await act(async () => { first.reject(new ApiError("private diagnostics", 503)); });
  expect(screen.getByRole("alert").textContent).toBe("Could not load your trips. Please retry.");
  expect(screen.queryByRole("status")).toBeNull(); expect(vi.getTimerCount()).toBe(0);
  expect(screen.getByRole("button", { name: "Account menu" })).toBeTruthy();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Retry trips" })); });
  expect(document.querySelector(".loading-revealed")).toBeNull();
  await advance(LOADING_REVEAL_DELAY_MS); expect(document.querySelector(".loading-revealed")).not.toBeNull();
  await act(async () => { retry.resolve([trip]); });
  expect(screen.getByRole("link", { name: trip.name })).toBeTruthy();
  expect(api.listTrips).toHaveBeenCalledTimes(2); expect(api.getMe).toHaveBeenCalledOnce();
});
it("a resolved 401 renders Sign in immediately with no trip content or leftover timers", async () => {
  const session = deferred<AuthState>(); vi.mocked(api.getMe).mockReturnValue(session.promise);
  await act(async () => { render(<AuthProvider><AuthForm mode="login" /></AuthProvider>); });
  await advance(COLD_START_MESSAGE_DELAY_MS);
  await act(async () => { session.reject(new ApiError("sign in required", 401)); });
  expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy();
  expect(screen.queryByRole("status")).toBeNull(); expect(api.listTrips).not.toHaveBeenCalled();
  expect(vi.getTimerCount()).toBe(0);
});
it("a session failure exits the travel scene and the existing session Retry recovers", async () => {
  const session = deferred<AuthState>(); vi.mocked(api.getMe).mockReturnValueOnce(session.promise).mockResolvedValueOnce(auth);
  await home(); await advance(COLD_START_MESSAGE_DELAY_MS);
  await act(async () => { session.reject(new ApiError("failure", 503)); });
  expect(screen.getByRole("alert").textContent).toBe("Could not check your sign-in. Please try again.");
  expect(screen.queryByRole("status")).toBeNull(); expect(api.listTrips).not.toHaveBeenCalled();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Retry sign-in check" })); });
  expect(screen.getByRole("link", { name: trip.name })).toBeTruthy();
  expect(api.getMe).toHaveBeenCalledTimes(2); expect(api.listTrips).toHaveBeenCalledOnce();
});
it("cleans up both timers on unmount before either fires", () => {
  const view = render(<LoadingState variant="session" />);
  expect(vi.getTimerCount()).toBe(2); view.unmount(); expect(vi.getTimerCount()).toBe(0);
});

it("a session resolved at 249ms cancels the traveler reveal without delaying Trips", async () => {
  const session = deferred<AuthState>(); vi.mocked(api.getMe).mockReturnValue(session.promise);
  await home(); await advance(LOADING_REVEAL_DELAY_MS - 1);
  expect(document.querySelector(".loading-revealed")).toBeNull();
  await act(async () => { session.resolve(auth); });
  expect(screen.getByRole("link", { name: trip.name })).toBeTruthy();
  expect(document.querySelector(".travel-loading-illustration")).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
  expect(api.getMe).toHaveBeenCalledOnce(); expect(api.listTrips).toHaveBeenCalledOnce();
});
it("StrictMode leaves one pair of timers and cleans both without extra status updates", async () => {
  const view = render(<StrictMode><LoadingState variant="session" /></StrictMode>);
  expect(vi.getTimerCount()).toBe(2);
  await advance(COLD_START_MESSAGE_DELAY_MS);
  expect(screen.getByRole("status").textContent).toBe("Starting TripTab…");
  expect(document.querySelectorAll(".travel-loading-illustration")).toHaveLength(1);
  view.unmount(); expect(vi.getTimerCount()).toBe(0);
});
