import { expect, test } from "@playwright/test";

test("traveler duplicates are rejected within one Trip while unique and cross-Trip names work", async ({ page }) => {
  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  await page.goto("/register");
  await page.getByLabel("Display name").fill("Organizer");
  await page.getByLabel("Email", { exact: true }).fill(`traveler-names-${suffix}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("Traveler names test password 123");
  await page.getByRole("button", { name: "Register", exact: true }).click();
  await expect(page.getByLabel("Trip name")).toBeVisible();
  await page.getByLabel("Trip name").fill(`Name integrity ${suffix}`);
  await page.getByRole("button", { name: "Create trip" }).click();
  const travelers = page.getByRole("region", { name: "Travelers", exact: true });
  const input = travelers.getByLabel("Traveler name");
  await input.fill(" Alice ");
  await travelers.getByRole("button", { name: "Add traveler" }).click();
  await expect(travelers.getByRole("group", { name: "Invitation for Alice", exact: true })).toHaveCount(1);
  for (const name of ["Alice", "alice", " Alice "]) {
    await input.fill(name);
    const response = page.waitForResponse((response) => response.request().method() === "POST" && response.url().endsWith("/members"));
    await travelers.getByRole("button", { name: "Add traveler" }).click();
    expect((await response).status()).toBe(409);
    await expect(travelers.locator("form").getByRole("alert")).toContainText("already exists in this trip");
    await expect(input).toHaveValue(name);
    await expect(travelers.locator(".traveler-row")).toHaveCount(2);
  }
  await input.fill("Bob");
  await travelers.getByRole("button", { name: "Add traveler" }).click();
  await expect(travelers.getByRole("group", { name: "Invitation for Bob", exact: true })).toBeVisible();
  await expect(travelers.locator(".traveler-row")).toHaveCount(3);
  await page.getByRole("link", { name: "All trips", exact: false }).click();
  await page.getByLabel("Trip name").fill(`Other name integrity ${suffix}`);
  await page.getByRole("button", { name: "Create trip" }).click();
  await input.fill("Alice");
  await travelers.getByRole("button", { name: "Add traveler" }).click();
  await expect(travelers.getByRole("group", { name: "Invitation for Alice", exact: true })).toBeVisible();
});
