import { expect, test, Page } from "@playwright/test";

async function register(page: Page, name: string) {
  const email = `${name.toLowerCase()}-${Date.now()}-${Math.random().toString(36).slice(2)}@example.com`;
  const response = await page.goto("/register");
  expect(response?.headers()["x-content-type-options"]).toBe("nosniff");
  expect(response?.headers()["referrer-policy"]).toBe("no-referrer");
  expect(response?.headers()["content-security-policy"]).toContain("frame-ancestors 'none'");
  await page.getByLabel("Display name").fill(name);
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill("TripTab test password 123");
  await page.getByRole("button", { name: "Register", exact: true }).click();
  await expect(page.getByLabel("Trip name")).toBeVisible();
  return email;
}

test("records Bob's real payment and refreshes the trip", async ({ page }) => {
  const email = await register(page, "Alice");
  await page.getByLabel("Trip name").fill(`Settle-up smoke ${Date.now()}`);
  await page.getByRole("button", { name: "Create trip" }).click();
  await expect(page).toHaveURL(/\/trips\/[^/]+$/);

  const travelers = page.getByRole("region", { name: "Travelers", exact: true });
  for (const name of ["Bob", "Charlie"]) {
    await travelers.getByLabel("Traveler name").fill(name);
    await travelers.getByRole("button", { name: "Add traveler" }).click();
    await expect(travelers.locator(".traveler-row").filter({ hasText: name })).toBeVisible();
  }
  await expect(travelers.locator(".traveler-row").filter({ hasText: "Alice" })).toContainText("Owner");
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
  const tripUrl = page.url();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto(tripUrl);
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill("TripTab test password 123");
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  await expect(page.getByLabel("Trip name")).toBeVisible();
  await page.goto(tripUrl);
  await expect(history).toContainText("Bob paid Alice");
  await expect(balances.locator(".balance-row").filter({ hasText: "Bob" })).toContainText("settled");

});

test("corrects an expense while preserving auditable history", async ({ page }) => {
  await register(page, "Alice");
  await page.getByLabel("Trip name").fill(`Correction smoke ${Date.now()}`);
  await page.getByRole("button", { name: "Create trip" }).click();
  await expect(page).toHaveURL(/\/trips\/[^/]+$/);
  const travelers = page.getByRole("region", { name: "Travelers", exact: true });
  for (const name of ["Bob", "Charlie"]) {
    await travelers.getByLabel("Traveler name").fill(name);
    await travelers.getByRole("button", { name: "Add traveler" }).click();
    await expect(travelers.locator(".traveler-row").filter({ hasText: name })).toBeVisible();
  }
  const form = page.getByRole("region", { name: "Add an expense", exact: true });
  await form.getByLabel("Description").fill("Dinner");
  await form.getByLabel("Amount (NT$)").fill("900");
  await form.getByLabel("Paid by").selectOption({ label: "Alice" });
  await form.getByLabel("When did it happen?").fill("2026-10-03T12:00");
  for (const name of ["Alice", "Bob", "Charlie"]) await form.getByRole("checkbox", { name, exact: true }).check();
  await form.getByRole("button", { name: "Add expense" }).click();
  const balances = page.getByRole("region", { name: "Balances", exact: true });
  await expect(balances.locator(".balance-row").filter({ hasText: "Alice" })).toContainText("gets back NT$600");
  const history = page.getByRole("region", { name: "Expense history", exact: true });
  await history.getByRole("button", { name: "Correct", exact: true }).click();
  const editor = history.getByRole("group", { name: "Correct expense" });
  await expect(editor).toContainText("original expense will remain in history");
  await expect(editor.getByLabel("Amount (NT$)")).toHaveValue("900");
  await editor.getByLabel("Amount (NT$)").fill("990");
  await editor.getByLabel("Reason").fill("Receipt total was 990");
  await editor.getByRole("button", { name: "Save correction" }).click();
  await expect(history.locator("article")).toHaveCount(2);
  const original = history.locator("article").filter({ hasText: "NT$900" });
  await expect(original).toContainText("Voided · excluded from current balances");
  await expect(original).toContainText("Receipt total was 990");
  await expect(original.getByRole("link", { name: "Replaced by another expense" })).toBeVisible();
  const replacement = history.locator("article").filter({ hasText: "NT$990" });
  await expect(replacement).toContainText("Active");
  await expect(replacement.getByRole("link", { name: "Replaces original expense" })).toBeVisible();
  await expect(balances.locator(".balance-row").filter({ hasText: "Alice" })).toContainText("gets back NT$660");
  for (const name of ["Bob", "Charlie"]) await expect(balances.locator(".balance-row").filter({ hasText: name })).toContainText("owes NT$330");
  await page.reload();
  await expect(original).toContainText("Voided");
  await expect(replacement).toContainText("Active");
});


test("a second account cannot open another account's private trip", async ({ page }) => {
  await register(page, "Alice");
  await page.getByLabel("Trip name").fill(`Private trip ${Date.now()}`);
  await page.getByRole("button", { name: "Create trip" }).click();
  await expect(page).toHaveURL(/\/trips\/[^/]+$/);
  const tripUrl = page.url();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await register(page, "Bob");
  await expect(page.getByText("No trips yet")).toBeVisible();
  await page.goto(tripUrl);
  await expect(page.getByText("We couldn’t find that trip.")).toBeVisible();
  await expect(page.getByRole("region", { name: "Expense history", exact: true })).toHaveCount(0);
});
