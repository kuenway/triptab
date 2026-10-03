import { afterEach, expect, it, vi } from "vitest";

import { api, ApiError, ExpenseInput, SettlementInput } from "../lib/api";

const expense: ExpenseInput = {
  description: "Dinner", amount: 990, payer_member_id: "alice", split_strategy: "equal",
  participant_member_ids: ["alice", "bob"], occurred_at: "2026-10-03T12:00:00Z",
};
const payment: SettlementInput = { from_member_id: "bob", to_member_id: "alice", amount: 200, occurred_at: expense.occurred_at };

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
