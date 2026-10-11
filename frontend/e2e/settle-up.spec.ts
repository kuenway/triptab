import { expect, test, Page } from "@playwright/test";
import { openExpense, openSection } from "./trip-navigation";

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
  // Exercise the real production-build rewrite with an authenticated cookie.
  for (const path of ["/api/v1/auth/me", "/api/v1/groups"]) {
    const api = await page.request.get(path);
    expect(api.status()).toBe(200);
    expect(api.headers()["cache-control"]).toBe("no-store");
    expect(api.headers()["cdn-cache-control"]).toBe("no-store");
    if (path.endsWith("/me")) expect((await api.json()).user.email).toBe(email);
  }
  return email;
}

test("records Bob's real payment and refreshes the trip", async ({ page }) => {
  const email = await register(page, "Alice");
  await page.getByLabel("Trip name").fill(`Settle-up smoke ${Date.now()}`);
  await page.getByRole("button", { name: "Create trip" }).click();
  await expect(page).toHaveURL(/\/trips\/[^/]+$/);

  await openSection(page, "Travelers");
  const travelers = page.getByRole("region", { name: "Travelers", exact: true });
  for (const name of ["Bob", "Charlie"]) {
    await travelers.getByLabel("Traveler name").fill(name);
    await travelers.getByRole("button", { name: "Add traveler" }).click();
    await expect(travelers.locator(".traveler-row").filter({ hasText: name })).toBeVisible();
  }
  await expect(travelers.locator(".traveler-row").filter({ hasText: "Alice" })).toContainText("Owner");
  await openSection(page, "Expenses");
  const expense = await openExpense(page);
  await expense.getByLabel("Description").fill("Dinner");
  await expense.getByLabel("Amount (NT$)").fill("900");
  await expense.getByLabel("Paid by").selectOption({ label: "Alice" });
  await expense.getByLabel("When did it happen?").fill("2026-10-03T12:00");
  for (const name of ["Alice", "Bob", "Charlie"]) await expense.getByRole("checkbox", { name, exact: true }).check();
  await expense.getByRole("button", { name: "Add expense" }).click();

  await openSection(page, "Balances");
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
  const history = page.getByRole("region", { name: "Current payments", exact: true });
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

  const currentPayments = history.getByRole("group", { name: "Current payments", exact: true });
  await currentPayments.getByRole("button", { name: "Edit" }).click();
  const paymentEditor = currentPayments.getByRole("group", { name: "Edit payment" });
  await expect(paymentEditor.getByLabel("Payment amount (NT$)")).toHaveValue("300");
  await paymentEditor.getByLabel("Payment amount (NT$)").fill("200");
  await paymentEditor.getByLabel("Reason").fill("Actual payment was 200");
  await paymentEditor.getByRole("button", { name: "Save changes" }).click();
  await expect(currentPayments.locator("article")).toHaveCount(1);
  await expect(currentPayments).toContainText("NT$200");
  await expect(currentPayments).not.toContainText("NT$300");
  const paymentHistory = history.locator("details.financial-history");
  await expect(paymentHistory).toHaveJSProperty("open", false);
  await currentPayments.getByRole("link", { name: "View edit history" }).click();
  await expect(paymentHistory).toContainText("Actual payment was 200");
  await expect(paymentHistory.getByRole("link", { name: "Replaced by another payment · NT$200" })).toBeVisible();
  await expect(balances.locator(".balance-row").filter({ hasText: "Bob" })).toContainText("owes NT$100");
  await currentPayments.getByRole("button", { name: "Delete payment" }).click();
  const deletePayment = currentPayments.getByRole("form", { name: "Delete payment" });
  await deletePayment.getByLabel("Reason").fill("Payment did not happen");
  await deletePayment.getByRole("button", { name: "Confirm delete payment" }).click();
  await expect(currentPayments.locator("article")).toHaveCount(0);
  await expect(paymentHistory.locator("article")).toHaveCount(2);
  await expect(paymentHistory).toContainText("Payment did not happen");
  await expect(balances.locator(".balance-row").filter({ hasText: "Bob" })).toContainText("owes NT$300");
  await expect(paymentHistory.locator("article").getByRole("button")).toHaveCount(0);

});

test("edits and deletes an expense while keeping previous versions in history", async ({ page }) => {
  await register(page, "Alice");
  await page.getByLabel("Trip name").fill(`Edit/history smoke ${Date.now()}`);
  await page.getByRole("button", { name: "Create trip" }).click();
  await expect(page).toHaveURL(/\/trips\/[^/]+$/);
  await openSection(page, "Travelers");
  const travelers = page.getByRole("region", { name: "Travelers", exact: true });
  for (const name of ["Bob", "Charlie"]) {
    await travelers.getByLabel("Traveler name").fill(name);
    await travelers.getByRole("button", { name: "Add traveler" }).click();
    await expect(travelers.locator(".traveler-row").filter({ hasText: name })).toBeVisible();
  }
  await openSection(page, "Expenses");
  const form = await openExpense(page);
  await form.getByLabel("Description").fill("Dinner");
  await form.getByLabel("Amount (NT$)").fill("900");
  await form.getByLabel("Paid by").selectOption({ label: "Alice" });
  await form.getByLabel("When did it happen?").fill("2026-10-03T12:00");
  for (const name of ["Alice", "Bob", "Charlie"]) await form.getByRole("checkbox", { name, exact: true }).check();
  await form.getByRole("button", { name: "Add expense" }).click();
  const tripUrl = page.url();
  await openSection(page, "Balances");
  const balances = page.getByRole("region", { name: "Balances", exact: true });
  await expect(balances.locator(".balance-row").filter({ hasText: "Alice" })).toContainText("gets back NT$600");
  await openSection(page, "Expenses");
  const region = page.getByRole("region", { name: "Current expenses", exact: true });
  const current = region.getByRole("group", { name: "Current expenses", exact: true });
  await current.getByRole("button", { name: "Edit", exact: true }).click();
  const editor = page.getByRole("dialog", { name: "Edit expense" });
  await expect(editor).toContainText("previous version stays in history");
  await expect(editor.getByLabel("Amount (NT$)")).toHaveValue("900");
  await expect(editor.getByLabel("Description")).toHaveValue("Dinner");
  await editor.getByLabel("Amount (NT$)").fill("990");
  await editor.getByLabel("Description").fill("Dinner updated");
  await editor.getByLabel("Reason").fill("Receipt total was 990");
  const correction = page.waitForResponse((response) => response.request().method() === "POST" && new URL(response.url()).pathname.endsWith("/corrections"));
  await editor.getByRole("button", { name: "Save changes" }).click();
  expect((await correction).status()).toBe(201);
  await expect(current.locator("article")).toHaveCount(1);
  await expect(current).toContainText("NT$990");
  await expect(current).not.toContainText("NT$900");
  await expect(current.getByText("Active", { exact: true })).toHaveCount(0);
  await expect(region.locator(".section-heading .count")).toHaveText("1");
  const history = region.locator("details.financial-history");
  const original = history.locator("article").filter({ hasText: "NT$900" });
  await expect(history).toHaveJSProperty("open", false);
  await expect(original).not.toBeVisible();
  await current.getByRole("link", { name: "View edit history" }).click();
  await expect(history).toHaveJSProperty("open", true);
  await expect(original).toContainText("Voided");
  await expect(original).toContainText("Receipt total was 990");
  await expect(original).toContainText("Recorded");
  await expect(original.getByRole("link", { name: "Replaced by another expense · NT$990" })).toBeVisible();
  await expect(original.getByRole("button")).toHaveCount(0);
  await original.getByRole("link", { name: "Replaced by another expense · NT$990" }).click();
  await openSection(page, "Balances");
  await expect(balances.locator(".balance-row").filter({ hasText: "Alice" })).toContainText("gets back NT$660");
  for (const name of ["Bob", "Charlie"]) await expect(balances.locator(".balance-row").filter({ hasText: name })).toContainText("owes NT$330");
  await page.goto(tripUrl);
  await expect(current.locator("article")).toHaveCount(1);
  await expect(history).toHaveJSProperty("open", false);
  const trash = current.getByRole("button", { name: "Delete expense", exact: true });
  await expect(trash.locator('svg[aria-hidden="true"]')).toHaveCount(1);
  await trash.click();
  const confirmation = current.getByRole("form", { name: "Delete expense" });
  await expect(confirmation).toContainText("keeps the original record in history");
  await confirmation.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(current).toContainText("NT$990");
  await trash.click();
  await confirmation.getByLabel("Reason").fill("Duplicate dinner entry");
  await confirmation.getByRole("button", { name: "Confirm delete expense" }).click();
  await expect(current.locator("article")).toHaveCount(0);
  await expect(current).toContainText("No current expenses");
  await expect(region.locator(".section-heading .count")).toHaveText("0");
  await openSection(page, "Balances");
  await expect(balances.locator(".balance-row").filter({ hasText: "Alice" })).toContainText("settled");
  for (const name of ["Bob", "Charlie"]) await expect(balances.locator(".balance-row").filter({ hasText: name })).toContainText("settled");
  await openSection(page, "Expenses");
  await region.getByText("Show expense history (2)").click();
  await expect(history.locator("article")).toHaveCount(2);
  await expect(history).toContainText("Duplicate dinner entry");
  await expect(history.locator("article").filter({ hasText: "NT$990" }).getByRole("link", { name: "Replaces an earlier expense · NT$900" })).toBeVisible();
  await expect(history.locator("article").getByRole("button")).toHaveCount(0);
  await page.reload();
  await expect(current.locator("article")).toHaveCount(0);
  await expect(history).toHaveJSProperty("open", false);
  await region.getByText("Show expense history (2)").click();
  await expect(history).toContainText("Duplicate dinner entry");
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
  await expect(page.getByRole("region", { name: "Current expenses", exact: true })).toHaveCount(0);
});
