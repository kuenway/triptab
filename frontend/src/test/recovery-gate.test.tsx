import { act, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AuthForm, AuthProvider } from "../components/auth";
import { ForgotPassword, ResetPassword } from "../components/password-recovery";
import { api, ApiError } from "../lib/api";
import { passwordRecoveryEnabled } from "../lib/feature-flags";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a> }));
vi.mock("../lib/api", async original => {
  const originalApi = await original<typeof import("../lib/api")>();
  return { ...originalApi, api: Object.fromEntries(Object.keys(originalApi.api).map(key => [key, vi.fn()])) };
});
beforeEach(() => {
  vi.resetAllMocks(); vi.stubEnv("NEXT_PUBLIC_TRIPTAB_PASSWORD_RECOVERY_ENABLED", undefined);
  history.replaceState(null, "", "/"); localStorage.clear(); sessionStorage.clear();
  vi.mocked(api.getMe).mockRejectedValue(new ApiError("sign in required", 401));
});
afterEach(() => vi.unstubAllEnvs());

it.each([undefined, "false", "invalid", "true"])("public visibility flag %s enables only literal true", value => {
  vi.stubEnv("NEXT_PUBLIC_TRIPTAB_PASSWORD_RECOVERY_ENABLED", value);
  expect(passwordRecoveryEnabled()).toBe(value === "true");
});
it.each([undefined, "false"])("disabled %s Sign in retains auth but hides Forgot password", async value => {
  vi.stubEnv("NEXT_PUBLIC_TRIPTAB_PASSWORD_RECOVERY_ENABLED", value);
  render(<AuthProvider><AuthForm mode="login" /></AuthProvider>);
  await screen.findByRole("heading", { name: "Sign in" });
  expect(screen.queryByRole("link", { name: "Forgot password?" })).toBeNull();
  expect(screen.getByLabelText("Email", { exact: true })).toBeTruthy();
  expect(screen.getByRole("link", { name: "Create an account" })).toBeTruthy();
});
it.each(["forgot", "reset"])("disabled direct %s route has no form or recovery request", async mode => {
  history.replaceState(null, "", "/" + mode + "-password#token=" + "a".repeat(43));
  render(mode === "forgot" ? <ForgotPassword /> : <ResetPassword />);
  expect(screen.getByRole("status").textContent).toBe("Password recovery is currently unavailable.");
  expect(screen.queryByRole("button")).toBeNull(); expect(document.querySelector("form")).toBeNull();
  expect(screen.getByRole("link", { name: "Back to Sign in" }).getAttribute("href")).toBe("/login");
  expect(location.hash).toBe("");
  await act(async () => {
    history.replaceState(null, "", "/" + mode + "-password#token=" + "b".repeat(43));
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
  expect(location.hash).toBe("");
  expect(localStorage.length + sessionStorage.length).toBe(0);
  expect(api.forgotPassword).not.toHaveBeenCalled(); expect(api.resetPassword).not.toHaveBeenCalled();
  expect(api.getMe).not.toHaveBeenCalled();
});
