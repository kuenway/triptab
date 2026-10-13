import { expect, test } from "@playwright/test";

test("delayed entry loading stays neutral, handles cold starts and respects reduced motion", async ({ page }, testInfo) => {
  await page.clock.install();
  let resolveSession!: () => void, resolveTrips!: () => void;
  const session = new Promise<void>(done => { resolveSession = done; });
  const trips = new Promise<void>(done => { resolveTrips = done; });
  await page.route("**/api/v1/auth/me", async route => {
    await session;
    await route.fulfill({ json: { user: { id: "loading-user", email: "loading@example.com", display_name: "Loading test", created_at: "2026-10-12T12:00:00Z" }, csrf_token: "loading-test-csrf" } });
  });
  await page.route("**/api/v1/groups", async route => {
    await trips;
    await route.fulfill({ json: [
      { id: "loading-trip-1", name: "Japan 2027", currency: "TWD", currency_scale: 0 },
      { id: "loading-trip-2", name: "A longer shared trip name", currency: "TWD", currency_scale: 0 },
    ] });
  });
  await page.goto("/");
  await expect(page.getByRole("status")).toHaveText("Loading TripTab");
  await expect(page.getByRole("heading", { name: "Sign in" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Your trips" })).toHaveCount(0);
  await expect(page.getByText("Loading…", { exact: true })).toHaveCount(0);
  await expect(page.locator(".loading-revealed .loading-surface")).toBeVisible();
  expect(await page.locator(".brand-dot").evaluate(element => getComputedStyle(element).animationName)).toBe("brand-dot-pulse");
  for (const width of [320, 375, 1280]) {
    await page.setViewportSize({ width, height: 812 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const card = (await page.locator(".loading-surface").boundingBox())!;
    expect(card.width).toBeLessThanOrEqual(440); expect(card.x).toBeGreaterThan(0);
    await page.screenshot({ path: testInfo.outputPath(`session-loading-${width}.png`) });
  }
  await page.clock.fastForward(5000);
  await expect(page.getByRole("status")).toHaveText("Starting TripTab…");
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const selector of [".brand-dot", ".skeleton-bar"]) expect(await page.locator(selector).first().evaluate(element => getComputedStyle(element).animationName)).toBe("none");
  await expect(page.locator(".loading-surface")).toBeVisible();
  resolveSession();
  await expect(page.getByRole("heading", { name: "Your trips" })).toBeVisible();
  await expect(page.getByRole("status")).toHaveText("Loading your trips");
  await expect(page.getByText("Starting TripTab…")).toHaveCount(0);
  await expect(page.locator(".loading-trips.loading-revealed .loading-surface")).toBeVisible();
  const skeletonHeight = (await page.locator(".skeleton-trip-list").boundingBox())!.height;
  for (const width of [375, 1280]) {
    await page.setViewportSize({ width, height: 812 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`trips-loading-${width}.png`) });
  }
  resolveTrips();
  await expect(page.getByRole("list", { name: "Your trips" }).getByRole("link")).toHaveCount(2);
  await expect(page.locator(".loading-state")).toHaveCount(0);
  expect(Math.abs((await page.locator(".trip-list").boundingBox())!.height - skeletonHeight)).toBeLessThan(3);
  expect(await page.locator(".brand-dot").evaluate(element => getComputedStyle(element).animationName)).toBe("none");
});
