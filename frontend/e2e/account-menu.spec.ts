import { expect, test } from "@playwright/test";

test("home account disclosure signs out and keeps Trip headers focused", async ({ page }, testInfo) => {
  const email = `account-${Date.now()}-a-long-email-address@example.com`, password = "TripTab account test password 123";
  await page.goto("/register");
  await page.getByLabel("Display name").fill("Katherine with a long account name");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Register", exact: true }).click();
  const trigger = page.getByRole("button", { name: "Account menu", exact: true });
  const account = page.getByRole("group", { name: "Your account", exact: true });
  for (const width of [375, 1280]) {
    await page.setViewportSize({ width, height: 812 });
    await expect(trigger).toHaveText("K"); await expect(trigger).toHaveAttribute("aria-expanded", "false");
    await expect(page.getByText(email, { exact: true })).toHaveCount(0);
    expect((await trigger.boundingBox())!.height).toBeGreaterThanOrEqual(44);
    await page.keyboard.press("Tab"); await trigger.focus(); expect(await trigger.evaluate(e => getComputedStyle(e).outlineStyle)).toBe("solid");
    await page.keyboard.press("Enter"); await expect(account.getByText(email, { exact: true })).toBeVisible();
    await expect(account.getByRole("button", { name: "Sign out", exact: true })).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const box = await account.boundingBox(); expect(box!.x).toBeGreaterThanOrEqual(0); expect(box!.x + box!.width).toBeLessThanOrEqual(width);
    await page.screenshot({ path: testInfo.outputPath(`account-${width}.png`) });
    await page.keyboard.press("Escape"); await expect(account).toHaveCount(0); await expect(trigger).toBeFocused();
    await trigger.click(); await page.getByRole("heading", { name: "Your trips", exact: true }).click({ position: { x: 2, y: 2 } });
    await expect(account).toHaveCount(0); await expect(trigger).toBeFocused();
    await trigger.click(); await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible();
    await page.getByLabel("Email", { exact: true }).fill(email); await page.getByLabel("Password", { exact: true }).fill(password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(trigger).toBeVisible();
  }
  await page.getByRole("button", { name: "+ New trip", exact: true }).click();
  await page.getByLabel("Trip name").fill("A Trip with a long name that stays readable without the account action");
  await page.getByRole("button", { name: "Create trip", exact: true }).click();
  await expect(page).toHaveURL(/\/trips\/[^/]+$/);
  for (const width of [375, 1280]) {
    await page.setViewportSize({ width, height: 812 });
    await expect(page.getByRole("button", { name: /Sign out|Log out|Account menu/ })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "← All trips", exact: true })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Trip sections" }).getByRole("link")).toHaveCount(4);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`trip-header-${width}.png`) });
  }
  await page.getByRole("link", { name: "← All trips", exact: true }).click(); await expect(trigger).toBeVisible();
});
