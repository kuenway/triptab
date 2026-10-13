import { expect, test } from "@playwright/test";

const auth = { user: { id: "loading-user", email: "loading@example.com", display_name: "Loading test", created_at: "2026-10-12T12:00:00Z" }, csrf_token: "loading-test-csrf" };
const trips = [
  { id: "loading-trip-1", name: "Japan 2027", currency: "TWD", currency_scale: 0 },
  { id: "loading-trip-2", name: "A longer shared trip name", currency: "TWD", currency_scale: 0 },
];

test("compact traveler loading resolves auth and Trips, handles cold starts, errors and reduced motion", async ({ page }, testInfo) => {
  await page.clock.install();
  await page.clock.pauseAt(new Date());
  let resolveSession!: () => void, resolveTrips!: () => void, resolveError!: () => void;
  const session = new Promise<void>(done => { resolveSession = done; });
  const list = new Promise<void>(done => { resolveTrips = done; });
  const failure = new Promise<void>(done => { resolveError = done; });
  let failTrips = false, listReads = 0;
  await page.route("**/api/v1/auth/me", async route => { await session; await route.fulfill({ json: auth }); });
  await page.route("**/api/v1/groups", async route => {
    listReads++;
    if (failTrips) { await failure; await route.fulfill({ status: 503, json: { detail: "Read failure" } }); }
    else { await list; await route.fulfill({ json: trips }); }
  });
  await page.goto("/");
  await expect(page.getByRole("status")).toHaveText("Getting things ready…");
  await expect(page.getByRole("heading", { name: "Sign in" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Your trips" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Account menu" })).toHaveCount(0);
  await page.clock.runFor(249);
  await expect(page.locator(".travel-loading-illustration")).not.toBeVisible();
  await page.clock.runFor(1);
  await expect(page.locator(".travel-loading-illustration")).toBeVisible();
  await expect(page.locator(".skeleton-bar")).toHaveCount(0);
  expect(await page.locator(".brand-dot").evaluate(element => getComputedStyle(element).animationName)).toBe("none");
  await expect(page.locator("svg.travel-loading-illustration")).toHaveAttribute("aria-hidden", "true");
  await expect(page.locator("svg.travel-loading-illustration")).toHaveAttribute("focusable", "false");
  expect(await page.locator(".travel-leg-front").evaluate(element => getComputedStyle(element).animationDuration)).toBe("1.6s");
  for (const width of [320, 375, 1280]) {
    await page.setViewportSize({ width, height: 812 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const card = (await page.locator(".loading-state").boundingBox())!;
    const illustration = (await page.locator(".travel-loading-illustration").boundingBox())!;
    expect(card.height).toBeLessThanOrEqual(260); expect(illustration.width).toBe(200);
    expect(Math.abs(illustration.x + illustration.width / 2 - width / 2)).toBeLessThan(2);
    await page.screenshot({ path: testInfo.outputPath(`session-loading-${width}.png`) });
  }
  const scene = page.locator(".travel-loading-illustration");
  for (const frame of [0, 400, 800, 1200, 1600]) {
    await scene.evaluate((element, time) => {
      for (const animation of element.getAnimations({ subtree: true })) { animation.pause(); animation.currentTime = time; }
    }, frame);
    await scene.screenshot({ path: testInfo.outputPath(`walk-frame-${frame}.png`) });
  }
  await scene.evaluate(element => { for (const animation of element.getAnimations({ subtree: true })) animation.play(); });
  await page.clock.runFor(4750);
  await expect(page.getByRole("status")).toHaveText("Starting TripTab…");
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const selector of [".travel-body", ".travel-suitcase", ".travel-leg-front", ".travel-leg-back", ".travel-ground", ".brand-dot"]) {
    expect(await page.locator(selector).evaluate(element => getComputedStyle(element).animationName)).toBe("none");
  }
  await expect(page.locator(".travel-loading-illustration")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("reduced-motion.png") });
  resolveSession();
  await expect(page.getByRole("heading", { name: "Your trips" })).toBeVisible();
  await expect(page.getByRole("status")).toHaveText("Getting things ready…");
  await expect(page.getByText("Starting TripTab…")).toHaveCount(0);
  await expect(page.getByText("No trips yet.")).toHaveCount(0);
  await page.clock.runFor(250);
  await expect(page.locator(".loading-trips .travel-loading-illustration")).toBeVisible();
  for (const width of [375, 1280]) {
    await page.setViewportSize({ width, height: 812 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`trips-loading-${width}.png`) });
  }
  resolveTrips();
  await expect(page.getByRole("list", { name: "Your trips" }).getByRole("link")).toHaveCount(2);
  await expect(page.locator(".loading-state")).toHaveCount(0);
  expect(listReads).toBe(1);
  failTrips = true;
  await page.reload();
  await expect(page.getByRole("status")).toHaveText("Getting things ready…");
  await page.clock.runFor(250);
  await expect(page.locator(".loading-trips .travel-loading-illustration")).toBeVisible();
  resolveError();
  await expect(page.getByRole("alert").filter({ hasText: "Could not load your trips" })).toBeVisible();
  await expect(page.locator(".travel-loading-illustration")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Account menu" })).toBeVisible();
  failTrips = false;
  await page.getByRole("button", { name: "Retry trips", exact: true }).click();
  await expect(page.getByRole("list", { name: "Your trips" }).getByRole("link")).toHaveCount(2);
  await expect(page.locator(".loading-state")).toHaveCount(0);
  expect(listReads).toBe(3);
});

test("fast signed-out resolution never reveals the travel animation or cold-start copy", async ({ page }) => {
  await page.clock.install();
  await page.clock.pauseAt(new Date());
  await page.addInitScript(() => {
    (window as Window & { loadingRevealed?: boolean }).loadingRevealed = false;
    new MutationObserver(() => {
      if (document.querySelector(".loading-revealed")) (window as Window & { loadingRevealed?: boolean }).loadingRevealed = true;
    }).observe(document, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });
  });
  await page.route("**/api/v1/auth/me", route => route.fulfill({ status: 401, json: { detail: "Authentication required." } }));
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Sign in", exact: true })).toBeVisible();
  await page.clock.runFor(5000);
  expect(await page.evaluate(() => (window as Window & { loadingRevealed?: boolean }).loadingRevealed)).toBe(false);
  await expect(page.locator(".travel-loading-illustration")).toHaveCount(0);
  await expect(page.getByText("Starting TripTab…")).toHaveCount(0);
});
