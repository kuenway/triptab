import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import AccountPage from "../app/account/page";
import { AccountMenu, AuthProvider } from "../components/auth";
import { api, ApiError, AuthState } from "../lib/api";
const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a> }));
vi.mock("../lib/api", async (original) => {
  const value = await original<typeof import("../lib/api")>();
  return { ...value, api: Object.fromEntries(Object.keys(value.api).map(key => [key, vi.fn()])) };
});
const state: AuthState = { user: { id: "alice", email: "alice@example.com", display_name: "Alice", created_at: "2026-10-12T12:00:00Z" }, csrf_token: "csrf" };
function account() { return render(<AuthProvider><AccountMenu /><AccountPage /></AuthProvider>); }
async function passwords() {
  await screen.findByLabelText("Current password");
  for (const [label, value] of [["Current password", "Old password 123"], ["New password", "New password 456"], ["Confirm new password", "New password 456"]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
  return screen.getByLabelText("Current password").closest("form")!;
}
beforeEach(() => { vi.resetAllMocks(); vi.mocked(api.getMe).mockResolvedValue(state); vi.mocked(api.changePassword).mockResolvedValue(undefined); });
it("protects Account and preserves initial auth loading", async () => {
  vi.mocked(api.getMe).mockRejectedValue(new ApiError("Sign in required", 401)); account();
  expect(screen.queryByLabelText("Name")).toBeNull(); await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
});
it("shows null name, immutable email, explanation and app-level navigation", async () => {
  vi.mocked(api.getMe).mockResolvedValue({ ...state, user: { ...state.user, display_name: null } }); account();
  expect(await screen.findByLabelText("Name")).toHaveProperty("value", "");
  expect(screen.getByText(/Existing Tripmate names won’t change/)).toBeTruthy();
  expect(screen.getByRole("link", { name: "← All trips" }).getAttribute("href")).toBe("/");
  expect(screen.queryByRole("navigation", { name: "Trip sections" })).toBeNull();
  expect(screen.queryByLabelText("Email")).toBeNull(); expect(screen.getByText(state.user.email)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Account menu" }));
  expect(screen.getByRole("button", { name: "Account menu" }).textContent).toBe("A");
  expect(screen.getByRole("link", { name: "Account" }).getAttribute("href")).toBe("/account");
  expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy();
});
it("saves Unicode name and updates menu identity without auth reload", async () => {
  vi.mocked(api.updateProfile).mockResolvedValue({ ...state, user: { ...state.user, display_name: "王 Alice" } }); account();
  const name = await screen.findByLabelText("Name"); fireEvent.change(name, { target: { value: " 王 Alice " } });
  fireEvent.submit(name.closest("form")!); expect(await screen.findByText("Name saved.")).toBeTruthy();
  expect(api.updateProfile).toHaveBeenCalledWith("王 Alice"); expect(api.getMe).toHaveBeenCalledOnce();
  const trigger = screen.getByRole("button", { name: "Account menu" }); expect(trigger.textContent).toBe("王"); fireEvent.click(trigger);
  expect(within(screen.getByRole("group", { name: "Your account" })).getByText("王 Alice")).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();
});
it("can clear the optional name without inventing a persisted fallback", async () => {
  vi.mocked(api.updateProfile).mockResolvedValue({ ...state, user: { ...state.user, display_name: null } }); account();
  const name = await screen.findByLabelText("Name"); fireEvent.change(name, { target: { value: "" } }); fireEvent.submit(name.closest("form")!);
  await screen.findByText("Name saved."); expect(api.updateProfile).toHaveBeenCalledWith(null);
});
it("preserves invalid name and associates server validation error", async () => {
  vi.mocked(api.updateProfile).mockRejectedValue(new ApiError("Name rejected", 422)); account();
  const input = await screen.findByLabelText("Name"); fireEvent.change(input, { target: { value: "Name" } }); fireEvent.submit(input.closest("form")!);
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Name rejected"); expect(input).toHaveProperty("value", "Name");
  expect(input.getAttribute("aria-invalid")).toBe("true"); expect(input.getAttribute("aria-describedby")).toContain("account-name-error");
});
it("does not retry an uncertain profile mutation and safely rechecks", async () => {
  vi.mocked(api.updateProfile).mockRejectedValue(new ApiError("Unavailable", 503)); account();
  const input = await screen.findByLabelText("Name"); fireEvent.submit(input.closest("form")!); await screen.findByRole("button", { name: "Check account" });
  fireEvent.submit(input.closest("form")!); expect(api.updateProfile).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "Check account" })); await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  expect(api.getMe).toHaveBeenCalledTimes(2);
});
it("blocks password mismatch and uses native password-manager semantics", async () => {
  account(); const form = await passwords(); fireEvent.change(screen.getByLabelText("Confirm new password"), { target: { value: "Different password 789" } });
  fireEvent.submit(form); expect(screen.getByText("New passwords do not match.")).toBeTruthy(); expect(api.changePassword).not.toHaveBeenCalled();
  expect(screen.getByLabelText("Current password").getAttribute("autocomplete")).toBe("current-password");
  expect(screen.getByLabelText("New password").getAttribute("autocomplete")).toBe("new-password");
});
it("clears password fields on success and keeps current account", async () => {
  account(); fireEvent.submit(await passwords()); await screen.findByText("Password changed. Other sessions have been signed out.");
  for (const label of ["Current password", "New password", "Confirm new password"]) expect(screen.getByLabelText(label)).toHaveProperty("value", "");
  expect(api.changePassword).toHaveBeenCalledWith("Old password 123", "New password 456"); expect(api.getMe).toHaveBeenCalledOnce();
});
it("incorrect current password is field-associated and retains input", async () => {
  vi.mocked(api.changePassword).mockRejectedValue(new ApiError("Current password is incorrect.", 422)); account(); fireEvent.submit(await passwords());
  await screen.findByText("Current password is incorrect."); const input = screen.getByLabelText("Current password");
  expect(input).toHaveProperty("value", "Old password 123"); expect(input.getAttribute("aria-invalid")).toBe("true");
});
it("guards duplicate password submissions and uncertain responses without retry", async () => {
  let reject!: (error: Error) => void; vi.mocked(api.changePassword).mockReturnValue(new Promise((_resolve, fail) => { reject = fail; }));
  account(); const form = await passwords(); fireEvent.submit(form); fireEvent.submit(form); expect(api.changePassword).toHaveBeenCalledOnce();
  reject(new ApiError("Network", 0)); await screen.findByText(/It may have changed/); fireEvent.submit(form); expect(api.changePassword).toHaveBeenCalledOnce();
  expect(screen.queryByRole("button", { name: "Change password" })).toBeNull(); fireEvent.click(screen.getByRole("button", { name: "Clear password fields" }));
  expect(screen.getByLabelText("Current password")).toHaveProperty("value", "");
});

it.each(["Choose a password different from your email.", "Choose a new password different from your current password."])("Change password associates policy rejection %s with the new field", async message => {
  vi.mocked(api.changePassword).mockRejectedValue(new ApiError(message, 422)); account(); fireEvent.submit(await passwords());
  await screen.findByText(message); const input = screen.getByLabelText("New password");
  expect(input).toHaveProperty("value", "New password 456");
  expect(input.getAttribute("aria-describedby")).toBe("password-error");
  expect(input.getAttribute("aria-invalid")).toBe("true");
  expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();
});
