import { expect, test } from "@playwright/test";
import { openSection } from "./trip-navigation";

test("Trip routes survive reload, browser history and direct links at mobile and desktop widths", async ({ page }, testInfo) => {
  const suffix = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const email = `navigation-${suffix}@example.com`;
  await page.goto("/register");
  await page.getByLabel("Display name").fill("Organizer");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill("TripTab navigation test 123");
  await page.getByRole("button", { name: "Register", exact: true }).click();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill("TripTab navigation test 123");
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  await page.getByRole("button", { name: "+ New trip", exact: true }).click();
  await page.getByLabel("Trip name").fill(`Navigation ${suffix}`);
  await page.getByRole("button", { name: "Create trip" }).click();
  await expect(page).toHaveURL(/\/trips\/[^/]+$/);
  const tripUrl = page.url();
  const nav = page.getByRole("navigation", { name: "Trip sections" });
  await expect(nav.getByRole("link", { name: "Expenses", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("button", { name: "Add expense", exact: true })).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Tripmates", exact: true })).toHaveCount(0);

  await openSection(page, "Balances");
  await expect(page).toHaveURL(tripUrl + "/balances");
  await page.reload();
  await expect(nav.getByRole("link", { name: "Balances", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("region", { name: "Balances", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add expense", exact: true })).toHaveCount(0);
  // Observe every DOM commit, not just the final screen: no fallback/auth/footer flash.
  await page.evaluate(() => {
    const shell = document.querySelector("main.trip-shell"), nav = document.querySelector(".trip-navigation"), header = shell?.querySelector("header");
    const failures: string[] = [];
    Object.assign(window, { tripTransitionFailures: failures });
    new MutationObserver(() => {
      if (document.querySelector("main.trip-shell") !== shell || document.querySelector(".trip-navigation") !== nav || shell?.querySelector("header") !== header) failures.push("shell remounted");
      if (document.querySelector(".auth-shell") || /Loading session|Loading section|Private trip · Financial history is preserved/.test(document.body.innerText)) failures.push("loading flash");
    }).observe(document.body, { childList: true, subtree: true, characterData: true });
  });
  let sessionRequests = 0, balanceRequests = 0;
  page.on("request", request => { const path = new URL(request.url()).pathname; if (path === "/api/v1/auth/me") sessionRequests++; if (path.endsWith("/balances") && path.startsWith("/api/v1/")) balanceRequests++; });
  await openSection(page, "Tripmates");
  await expect(page).toHaveURL(tripUrl + "/travelers");
  await openSection(page, "History");
  await expect(page).toHaveURL(tripUrl + "/history");
  await expect(page.getByRole("heading", { name: "History", exact: true })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(tripUrl + "/travelers");
  await expect(page.getByRole("region", { name: "Tripmates", exact: true })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(tripUrl + "/balances");
  await page.goBack();
  await expect(page).toHaveURL(tripUrl);
  await page.goForward();
  await expect(page).toHaveURL(tripUrl + "/balances");
  for (const name of ["Tripmates", "History", "Expenses", "Balances", "Tripmates", "History"] as const) await openSection(page, name);
  expect(await page.evaluate(() => (window as unknown as {tripTransitionFailures:string[]}).tripTransitionFailures)).toEqual([]);
  expect(sessionRequests).toBe(0); expect(balanceRequests).toBe(0);
  await page.goto(tripUrl);
  await expect(nav.getByRole("link", { name: "Expenses", exact: true })).toHaveAttribute("aria-current", "page");

  await page.setViewportSize({ width: 375, height: 812 });
  await openSection(page, "Tripmates");
  for (const name of ["Bob", "Charlie", "A traveler with a longer display name", "Guest Four"]) {
    await page.getByLabel("Tripmate name").fill(name);
    await page.getByRole("button", { name: "Add tripmate", exact: true }).click();
    await expect(page.getByRole("group", { name: `Tripmate ${name}`, exact: true })).toBeVisible();
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const boxes = await nav.getByRole("link").evaluateAll((links) => links.map((link) => ({ y: link.getBoundingClientRect().y, height: link.getBoundingClientRect().height, width: link.getBoundingClientRect().width })));
  expect(new Set(boxes.map((box) => box.y)).size).toBe(1);
  expect(boxes.every((box) => box.width >= 44 && box.height >= 44)).toBe(true);
  await expect(nav.locator("svg")).toHaveCount(4);
  expect(await nav.evaluate((element) => getComputedStyle(element).position)).toBe("fixed");
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  const end = await page.locator(".tripmates-section .inline-form").boundingBox();
  const navBox = await nav.boundingBox();
  expect(end!.y + end!.height).toBeLessThanOrEqual(navBox!.y);
  await page.screenshot({ path: testInfo.outputPath("trip-mobile.png"), fullPage: true });
  const historyLink = nav.getByRole("link", { name: "History", exact: true });
  await page.keyboard.press("Tab");
  await historyLink.focus();
  expect(await historyLink.evaluate((element) => getComputedStyle(element).outlineStyle)).toBe("solid");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(tripUrl + "/history");
  await expect(historyLink).toHaveAttribute("aria-current", "page");
  await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);

  await page.setViewportSize({ width: 1280, height: 900 });
  await openSection(page, "Expenses");
  expect(await nav.evaluate((element) => getComputedStyle(element).position)).toBe("static");
  const desktopBoxes = await nav.getByRole("link").evaluateAll((links) => links.map((link) => link.getBoundingClientRect().y));
  expect(new Set(desktopBoxes).size).toBe(1);
  expect((await page.locator(".trip-shell").boundingBox())!.width).toBeLessThanOrEqual(1104);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("trip-desktop.png"), fullPage: true });

  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.goto(tripUrl + "/balances");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Trip sections" })).toHaveCount(0);
});

test("an uncached slow section retains Expenses and the shell until History is ready", async ({ page }) => {
  await page.goto("/register");
  await page.getByLabel("Display name").fill("Navigation owner");
  await page.getByLabel("Email", { exact: true }).fill(`slow-navigation-${Date.now()}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("TripTab slow navigation test 123");
  await page.getByRole("button", { name: "Register", exact: true }).click();
  await expect(page.getByRole("button", { name: "+ New trip", exact: true })).toBeVisible();
  let release!: () => void, captured!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const pending = new Promise<void>(resolve => { captured = resolve; });
  await page.route("**/trips/*/history*", async route => {
    if (route.request().headers()["rsc"] === "1") { captured(); await gate; }
    await route.continue();
  });
  try {
    await page.getByRole("button", { name: "+ New trip", exact: true }).click();
    await page.getByLabel("Trip name").fill("Slow section navigation");
    await page.getByRole("button", { name: "Create trip" }).click();
    await expect(page.getByRole("heading", { name: "Expenses", exact: true })).toBeVisible();
    const nav = page.getByRole("navigation", { name: "Trip sections" });
    await nav.getByRole("link", { name: "History", exact: true }).click();
    await pending;
    await expect(page.getByRole("heading", { name: "Expenses", exact: true })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Expenses", exact: true })).toHaveAttribute("aria-current", "page");
    await expect(nav.getByRole("link", { name: "History", exact: true })).not.toHaveAttribute("aria-current", "page");
    await expect(page.locator(".auth-shell")).toHaveCount(0);
    await expect(page.getByText(/Loading session|Loading section|Private trip · Financial history is preserved/)).toHaveCount(0);
    release();
    await expect(page.getByRole("heading", { name: "History", exact: true })).toBeVisible();
    await expect(nav.getByRole("link", { name: "History", exact: true })).toHaveAttribute("aria-current", "page");
  } finally { release(); await page.unrouteAll({ behavior: "wait" }); }
});
