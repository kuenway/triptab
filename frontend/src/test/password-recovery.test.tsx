import { fireEvent, render, screen } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { AuthForm, AuthProvider } from "../components/auth";
import { ForgotPassword, ResetPassword } from "../components/password-recovery";
import { api, ApiError } from "../lib/api";
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }));
vi.mock("next/link", () => ({ default: ({ href, children, className }: { href: string; children: ReactNode; className?: string }) => <a className={className} href={href}>{children}</a> }));
vi.mock("../lib/api", async original => {
  const value = await original<typeof import("../lib/api")>();
  return { ...value, api: Object.fromEntries(Object.keys(value.api).map(key => [key, vi.fn()])) };
});
const token = "a".repeat(43);
beforeEach(() => { vi.resetAllMocks(); history.replaceState(null, "", "/"); localStorage.clear(); sessionStorage.clear(); vi.mocked(api.getMe).mockRejectedValue(new ApiError("Sign in required", 401)); vi.mocked(api.forgotPassword).mockResolvedValue({ message: "generic" }); vi.mocked(api.resetPassword).mockResolvedValue(undefined); });
function page(children: ReactNode) { return render(<AuthProvider>{children}</AuthProvider>); }
async function resetForm() {
  history.replaceState(null, "", "/reset-password#token=" + token); page(<StrictMode><ResetPassword /></StrictMode>);
  await screen.findByLabelText("New password");
  for (const label of ["New password", "Confirm new password"]) fireEvent.change(screen.getByLabelText(label), { target: { value: "Recovered password 123" } });
  return screen.getByLabelText("New password").closest("form")!;
}
it("Sign in has a secondary Forgot link; registration keeps its existing flow", async () => {
  const view = page(<AuthForm mode="login" />); await screen.findByRole("heading", { name: "Sign in" });
  expect(screen.getByRole("link", { name: "Forgot password?" }).getAttribute("href")).toBe("/forgot-password"); view.unmount();
  page(<AuthForm mode="register" />); await screen.findByRole("heading", { name: "Create your account" }); expect(screen.queryByRole("link", { name: "Forgot password?" })).toBeNull();
});
it.each(["known@example.com", "unknown@example.com"])("forgot %s uses identical generic confirmation", async email => {
  page(<ForgotPassword />); const field = screen.getByLabelText("Email"); fireEvent.change(field, { target: { value: email } }); fireEvent.submit(field.closest("form")!);
  expect(await screen.findByRole("heading", { name: "Check your email" })).toBeTruthy(); expect(screen.getByRole("status").textContent).toBe("If an account exists for this email, we’ve sent a password reset link.");
  expect(api.forgotPassword).toHaveBeenCalledWith(email); expect(screen.queryByRole("navigation")).toBeNull(); expect(screen.getByRole("link", { name: "Back to Sign in" }).getAttribute("href")).toBe("/login");
});
it("forgot guards duplicate submission and safely presents rate limits", async () => {
  let reject!: (cause: Error) => void; vi.mocked(api.forgotPassword).mockReturnValue(new Promise((_ok, fail) => { reject = fail; }));
  page(<ForgotPassword />); const field = screen.getByLabelText("Email"); fireEvent.change(field, { target: { value: "alice@example.com" } }); fireEvent.submit(field.closest("form")!); fireEvent.submit(field.closest("form")!); expect(api.forgotPassword).toHaveBeenCalledOnce();
  reject(new ApiError("too many", 429)); expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Too many requests. Please wait before requesting another link."); expect(field.getAttribute("aria-describedby")).toBe("forgot-error");
});
it("forgot network uncertainty never auto-resubmits or exposes provider errors", async () => {
  vi.mocked(api.forgotPassword).mockRejectedValue(new ApiError("secret provider failure", 503)); page(<ForgotPassword />); fireEvent.submit(screen.getByLabelText("Email").closest("form")!); await screen.findByText(/Check your email before requesting another link/); expect(api.forgotPassword).toHaveBeenCalledOnce(); expect(screen.queryByText(/secret provider/)).toBeNull();
});
it("captures fragment once even in StrictMode, removes it and never stores token", async () => {
  await resetForm(); expect(location.hash).toBe(""); expect(location.search).toBe(""); expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0); expect(api.resetPassword).not.toHaveBeenCalled();
  expect(screen.getByLabelText("New password").getAttribute("autocomplete")).toBe("new-password"); expect(screen.getByLabelText("Confirm new password").getAttribute("autocomplete")).toBe("new-password"); expect(screen.queryByLabelText("Current password")).toBeNull();
});
it("missing or malformed fragment never enables a reset or sends empty token", async () => {
  history.replaceState(null, "", "/reset-password#token=invalid"); page(<ResetPassword />); await screen.findByText("This reset link is invalid or has expired."); expect(screen.queryByRole("button", { name: "Reset password" })).toBeNull(); expect(api.resetPassword).not.toHaveBeenCalled();
});
it("mismatched reset passwords have associated field feedback without API call", async () => {
  const form = await resetForm(); fireEvent.change(screen.getByLabelText("Confirm new password"), { target: { value: "Different password 456" } }); fireEvent.submit(form);
  expect(screen.getByText("New passwords do not match.")).toBeTruthy(); expect(api.resetPassword).not.toHaveBeenCalled(); expect(screen.getByLabelText("Confirm new password").getAttribute("aria-describedby")).toBe("reset-error");
});
it("reset success clears form/token and asks for explicit Sign in without login", async () => {
  fireEvent.submit(await resetForm()); await screen.findByRole("heading", { name: "Password reset" }); expect(api.resetPassword).toHaveBeenCalledWith(token, "Recovered password 123"); expect(api.login).not.toHaveBeenCalled(); expect(screen.queryByLabelText("New password")).toBeNull(); expect(screen.getByRole("link", { name: "Sign in" }).getAttribute("href")).toBe("/login");
});
it.each(["invalid", "expired", "consumed"])("%s token has one neutral unavailable state", async () => {
  vi.mocked(api.resetPassword).mockRejectedValue(new ApiError("This reset link is invalid or has expired.", 400)); fireEvent.submit(await resetForm()); await screen.findByText("This reset link is invalid or has expired."); expect(screen.queryByLabelText("New password")).toBeNull(); expect(screen.getByRole("link", { name: "Request a new reset link" }).getAttribute("href")).toBe("/forgot-password");
});
it("server password-policy rejection keeps input with field-associated feedback", async () => {
  vi.mocked(api.resetPassword).mockRejectedValue(new ApiError("Password rejected", 422)); fireEvent.submit(await resetForm()); await screen.findByText("Password rejected"); expect(screen.getByLabelText("New password")).toHaveProperty("value", "Recovered password 123");
});
it("uncertain reset clears secrets and blocks automatic/duplicate retries", async () => {
  vi.mocked(api.resetPassword).mockRejectedValue(new ApiError("network failure", 0)); const form = await resetForm(); fireEvent.submit(form); fireEvent.submit(form); await screen.findByText(/Try signing in with your new password/); expect(api.resetPassword).toHaveBeenCalledOnce(); expect(screen.queryByRole("button", { name: "Reset password" })).toBeNull(); expect(screen.queryByLabelText("New password")).toBeNull();
});

it("a second email fragment on the mounted page replaces cleared recovery context", async () => {
  fireEvent.submit(await resetForm()); await screen.findByRole("heading", { name: "Password reset" });
  const replacement = "b".repeat(43);
  history.replaceState(null, "", "/reset-password#token=" + replacement);
  fireEvent(window, new HashChangeEvent("hashchange"));
  await screen.findByLabelText("New password"); expect(location.hash).toBe("");
  expect(screen.getByLabelText("New password")).toHaveProperty("value", "");
  for (const label of ["New password", "Confirm new password"]) fireEvent.change(screen.getByLabelText(label), { target: { value: "Another recovery password 456" } });
  fireEvent.submit(screen.getByLabelText("New password").closest("form")!);
  await screen.findByRole("heading", { name: "Password reset" });
  expect(api.resetPassword).toHaveBeenLastCalledWith(replacement, "Another recovery password 456");
  expect(localStorage.length + sessionStorage.length).toBe(0);
});

it.each(["Choose a password different from your email.", "Choose a new password different from your current password."])("reset policy feedback %s preserves the captured token for a corrected submission", async message => {
  vi.mocked(api.resetPassword).mockRejectedValueOnce(new ApiError(message, 422)).mockResolvedValue(undefined);
  fireEvent.submit(await resetForm()); await screen.findByText(message);
  const input = screen.getByLabelText("New password");
  expect(input.getAttribute("aria-describedby")).toBe("reset-error");
  expect(input).toHaveProperty("value", "Recovered password 123");
  for (const label of ["New password", "Confirm new password"]) fireEvent.change(screen.getByLabelText(label), { target: { value: "correct horse battery staple" } });
  fireEvent.submit(input.closest("form")!); await screen.findByRole("heading", { name: "Password reset" });
  expect(api.resetPassword).toHaveBeenLastCalledWith(token, "correct horse battery staple");
  expect(location.hash).toBe("");
});
