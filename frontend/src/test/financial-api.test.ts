import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { api, ApiError, ExpenseInput, SettlementInput } from "../lib/api";

const expense: ExpenseInput = {
  description: "Dinner", amount: 990, payer_member_id: "alice", split_strategy: "equal",
  participant_member_ids: ["alice", "bob"], occurred_at: "2026-10-03T12:00:00Z",
};
const payment: SettlementInput = { from_member_id: "bob", to_member_id: "alice", amount: 200, occurred_at: expense.occurred_at };

beforeEach(async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ user: { id: "alice" }, csrf_token: "csrf-test" }), { status: 200 })));
  await api.getMe();
});
afterEach(() => vi.unstubAllGlobals());

it.each(["expense void", "expense correction", "payment void", "payment correction"])("posts the complete %s request through the API client", async (operation) => {
  const result = { id: "record", status: operation.endsWith("void") ? "voided" : "active", replaces_id: "original" };
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(result), { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  const body: { reason: string; replacement?: ExpenseInput | SettlementInput } = { reason: "Wrong amount" };
  let actual;
  if (operation === "expense void") actual = await api.voidExpense("trip", "original", body.reason);
  else if (operation === "payment void") actual = await api.voidSettlement("trip", "original", body.reason);
  else if (operation === "expense correction") { body.replacement = expense; actual = await api.correctExpense("trip", "original", body.reason, expense); }
  else { body.replacement = payment; actual = await api.correctSettlement("trip", "original", body.reason, payment); }
  expect(actual).toEqual(result);
  expect(fetch).toHaveBeenCalledWith(`/api/v1/groups/trip/${operation.startsWith("expense") ? "expenses" : "settlements"}/original/${operation.endsWith("void") ? "void" : "corrections"}`, expect.objectContaining({ method: "POST", body: JSON.stringify(body), cache: "no-store" }));
});

it("preserves conflict status and safe API error text", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "record already voided or corrected" }), { status: 409 })));
  await expect(api.voidExpense("trip", "original", "Fix")).rejects.toEqual(new ApiError("record already voided or corrected", 409));
});

it("adds the session CSRF header to every authenticated mutation", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "trip" }), { status: 201 }));
  vi.stubGlobal("fetch", fetch);
  await api.createTrip("Private trip");
  expect(fetch).toHaveBeenCalledWith("/api/v1/groups", expect.objectContaining({ credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRF-Token": "csrf-test" } }));
});

it("uses auth/me to recover CSRF after logout and page bootstrap", async () => {
  const fetch = vi.fn()
    .mockResolvedValueOnce(new Response(null, { status: 204 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ user: { id: "alice" }, csrf_token: "new-csrf" }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ id: "trip" }), { status: 201 }));
  vi.stubGlobal("fetch", fetch);
  await api.logout();
  await api.createTrip("Private trip");
  expect(fetch.mock.calls.map((call) => call[0])).toEqual(["/api/v1/auth/logout", "/api/v1/auth/me", "/api/v1/groups"]);
  expect(fetch.mock.calls[2][1].headers["X-CSRF-Token"]).toBe("new-csrf");
});

it("notifies the auth provider when an API session expires", async () => {
  const expired = vi.fn();
  window.addEventListener("triptab:auth-expired", expired);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "sign in required" }), { status: 401 })));
  try {
    await expect(api.listTrips()).rejects.toEqual(new ApiError("sign in required", 401));
    expect(expired).toHaveBeenCalledOnce();
  } finally {
    window.removeEventListener("triptab:auth-expired", expired);
  }
});

it("keeps an existing session's CSRF state when login credentials are wrong", async () => {
  const expired = vi.fn();
  window.addEventListener("triptab:auth-expired", expired);
  const fetch = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "invalid email or password" }), { status: 401 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ id: "trip" }), { status: 201 }));
  vi.stubGlobal("fetch", fetch);
  try {
    await expect(api.login("alice@example.com", "Wrong password 123")).rejects.toEqual(new ApiError("invalid email or password", 401));
    expect(expired).not.toHaveBeenCalled();
    await api.createTrip("Still signed in");
    expect(fetch.mock.calls[1][1].headers["X-CSRF-Token"]).toBe("csrf-test");
  } finally {
    window.removeEventListener("triptab:auth-expired", expired);
  }
});
