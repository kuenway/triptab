import { expect, test } from "@playwright/test";

test("records Bob's real payment and refreshes the trip", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Trip name").fill(`Settle-up smoke ${Date.now()}`);
  await page.getByRole("button", { name: "Create trip" }).click();
  await expect(page).toHaveURL(/\/trips\/[^/]+$/);

  const travelers = page.getByRole("region", { name: "Travelers", exact: true });
  for (const name of ["Alice", "Bob", "Charlie"]) {
    await travelers.getByLabel("Traveler name").fill(name);
    await travelers.getByRole("button", { name: "Add traveler" }).click();
    await expect(travelers.locator(".traveler-row").filter({ hasText: name })).toBeVisible();
  }
  const expense = page.getByRole("region", { name: "Add an expense", exact: true });
  await expense.getByLabel("Description").fill("Dinner");
  await expense.getByLabel("Amount (NT$)").fill("900");
  await expense.getByLabel("Paid by").selectOption({ label: "Alice" });
  await expense.getByLabel("When did it happen?").fill("2026-10-03T12:00");
  for (const name of ["Alice", "Bob", "Charlie"]) await expense.getByRole("checkbox", { name, exact: true }).check();
  await expense.getByRole("button", { name: "Add expense" }).click();

  const suggestions = page.getByRole("region", { name: "Suggested payments", exact: true });
  const bobSuggestion = suggestions.locator(".suggestion-item").filter({ hasText: "Bob → Alice" });
  await expect(bobSuggestion).toContainText("NT$300");
  await bobSuggestion.getByRole("button", { name: "Mark as paid" }).click();
  const confirmation = suggestions.getByRole("group", { name: "Record payment?" });
  await expect(confirmation).toContainText("TripTab does not transfer money.");
  await confirmation.getByLabel("When did the payment happen?").fill("2026-10-03T12:30");
  await confirmation.getByRole("button", { name: "Record payment", exact: true }).click();

  const balances = page.getByRole("region", { name: "Balances", exact: true });
  await expect(balances.locator(".balance-row").filter({ hasText: "Bob" })).toContainText("settled");
  await expect(balances.locator(".balance-row").filter({ hasText: "Alice" })).toContainText("gets back NT$300");
  await expect(balances.locator(".balance-row").filter({ hasText: "Charlie" })).toContainText("owes NT$300");
  await expect(suggestions.locator(".suggestion-item")).toHaveCount(1);
  await expect(suggestions.locator(".suggestion-item")).toContainText("Charlie → Alice");
  const history = page.getByRole("region", { name: "Payment history", exact: true });
  await expect(history).toContainText("Bob paid Alice");
  await expect(history).toContainText("NT$300");
  await page.reload();
  await expect(history).toContainText("Bob paid Alice");
  await expect(balances.locator(".balance-row").filter({ hasText: "Bob" })).toContainText("settled");
});
