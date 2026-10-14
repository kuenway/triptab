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
  expect(await page.locator(".travel-leg-front .travel-thigh").evaluate(element => getComputedStyle(element).animationDuration)).toBe("1.6s");
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
  for (const frame of [0, 200, 400, 600, 800, 1000, 1200, 1400, 1600]) {
    await scene.evaluate((element, time) => {
      for (const animation of element.getAnimations({ subtree: true })) { animation.pause(); animation.currentTime = time; }
    }, frame);
    await scene.screenshot({ path: testInfo.outputPath(`walk-frame-${frame}.png`) });
  }
  await scene.evaluate(element => { for (const animation of element.getAnimations({ subtree: true })) animation.play(); });
  await page.clock.runFor(4750);
  await expect(page.getByRole("status")).toHaveText("Starting TripTab…");
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const selector of [".travel-body", ".travel-suitcase", ".travel-leg-front .travel-thigh", ".travel-leg-front .travel-shin", ".travel-leg-front .travel-foot", ".travel-leg-back .travel-thigh", ".travel-leg-back .travel-shin", ".travel-leg-back .travel-foot", ".travel-ground", ".brand-dot"]) {
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


test("jointed walk alternates contact and swing without stretching, clipping or moving reduced-motion joints", async ({ page }) => {
  await page.clock.install();
  await page.clock.pauseAt(new Date());
  await page.route("**/api/v1/auth/me", async () => {});
  await page.goto("/");
  await page.clock.runFor(250);
  const scene = page.locator(".loading-revealed .travel-loading-illustration");
  await expect(scene).toBeVisible();
  for (const side of ["front", "back"]) {
    for (const joint of ["thigh", "shin", "foot"]) {
      const style = await scene.locator(`.travel-leg-${side} .travel-${joint}`).evaluate(element => {
        const style = getComputedStyle(element);
        return { duration: style.animationDuration, delay: style.animationDelay, name: style.animationName };
      });
      expect(style.duration).toBe("1.6s");
      expect(style.delay).toBe(side === "front" ? "0s" : "-0.8s");
      expect(style.name).not.toBe("none");
    }
  }
  async function pose(time: number) {
    return scene.evaluate((element, time) => {
      const svg = element as SVGSVGElement;
      for (const animation of svg.getAnimations({ subtree: true })) { animation.pause(); animation.currentTime = time; }
      const point = (node: SVGGraphicsElement, x = 0, y = 0) => {
        const result = new DOMPoint(x, y).matrixTransform(node.getCTM()!).matrixTransform(svg.getCTM()!.inverse());
        return { x: result.x, y: result.y };
      };
      const legs = Array.from(svg.querySelectorAll<SVGGElement>(".travel-leg")).map(leg => {
        const thigh = leg.querySelector<SVGGElement>(".travel-thigh")!;
        const shin = leg.querySelector<SVGGElement>(".travel-shin")!;
        const foot = leg.querySelector<SVGGElement>(".travel-foot")!;
        const upper = thigh.querySelector<SVGPathElement>("path")!, lower = shin.querySelector<SVGPathElement>("path")!;
        const upperEnd = upper.getPointAtLength(upper.getTotalLength()), lowerEnd = lower.getPointAtLength(lower.getTotalLength());
        const shoe = foot.querySelector<SVGPathElement>("path")!;
        const sole = shoe.getPointAtLength(shoe.getTotalLength());
        const footBox = foot.getBoundingClientRect(), svgBox = svg.getBoundingClientRect();
        const kneeMatrix = new DOMMatrix(getComputedStyle(shin).transform);
        return {
          side: leg.dataset.leg, hip: point(thigh), knee: point(shin), ankle: point(foot),
          upperEnd: point(upper, upperEnd.x, upperEnd.y), lowerEnd: point(lower, lowerEnd.x, lowerEnd.y),
          shoeDirection: point(foot, 1, 0), sole: point(shoe, sole.x, sole.y),
          kneeAngle: Math.atan2(kneeMatrix.b, kneeMatrix.a),
          dark: [leg, ...leg.querySelectorAll("g, path")].every(node => {
            const style = getComputedStyle(node);
            return style.stroke === getComputedStyle(svg).color && style.opacity === "1" && style.strokeOpacity === "1";
          }),
          clipped: footBox.left < svgBox.left || footBox.right > svgBox.right || footBox.bottom > svgBox.bottom,
        };
      });
      return { legs, groundY: svg.querySelector<SVGPathElement>(".travel-ground")!.getBBox().y };
    }, time);
  }
  const distance = (a: { x: number; y: number }, b: { x: number; y: number }) => Math.hypot(a.x - b.x, a.y - b.y);
  const start = await pose(0), halfway = await pose(800), end = await pose(1600);
  const left = (p: typeof start) => p.legs.find(leg => leg.side === "left")!;
  const right = (p: typeof start) => p.legs.find(leg => leg.side === "right")!;
  expect(left(start).ankle.x).toBeGreaterThan(right(start).ankle.x);
  expect(right(halfway).ankle.x).toBeGreaterThan(left(halfway).ankle.x);
  expect(distance(left(start).ankle, right(halfway).ankle)).toBeLessThan(.01);
  expect(distance(right(start).ankle, left(halfway).ankle)).toBeLessThan(.01);
  for (let i = 0; i < start.legs.length; i++) expect(distance(start.legs[i].ankle, end.legs[i].ankle)).toBeLessThan(.01);
  const passingA = await pose(400), passingB = await pose(1200);
  expect(right(passingA).ankle.y).toBeLessThan(left(passingA).ankle.y - 3);
  expect(left(passingB).ankle.y).toBeLessThan(right(passingB).ankle.y - 3);
  expect(right(passingA).kneeAngle).toBeGreaterThan(left(passingA).kneeAngle);
  expect(left(passingB).kneeAngle).toBeGreaterThan(right(passingB).kneeAngle);
  // Sample the whole cycle, including intermediate poses and the loop boundary.
  for (let time = 0; time <= 1600; time += 50) {
    const current = await pose(time);
    for (let i = 0; i < current.legs.length; i++) {
      const leg = current.legs[i], initial = start.legs[i];
      expect(distance(leg.hip, leg.knee)).toBeCloseTo(distance(initial.hip, initial.knee), 4);
      expect(distance(leg.knee, leg.ankle)).toBeCloseTo(distance(initial.knee, initial.ankle), 4);
      expect(distance(leg.upperEnd, leg.knee)).toBeLessThan(.01);
      expect(distance(leg.lowerEnd, leg.ankle)).toBeLessThan(.01);
      expect(leg.kneeAngle).toBeGreaterThanOrEqual(0);
      expect(leg.kneeAngle).toBeLessThan(Math.PI / 2);
      expect(leg.shoeDirection.x).toBeGreaterThan(leg.ankle.x);
      expect(leg.shoeDirection.y).toBeCloseTo(leg.ankle.y, 4);
      expect(leg.clipped).toBe(false);
      expect(leg.dark).toBe(true);
    }
    expect(current.groundY - Math.max(...current.legs.map(leg => leg.sole.y))).toBeLessThan(7);
  }
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(await scene.evaluate(element => element.getAnimations({ subtree: true }).length)).toBe(0);
  const still = await pose(0);
  expect(still.legs.every(leg => leg.dark)).toBe(true);
  await page.clock.runFor(1600);
  expect((await pose(1600)).legs).toEqual(still.legs);
  expect(left(still).ankle.x).toBeGreaterThan(right(still).ankle.x);
  await expect(scene).toHaveAttribute("aria-hidden", "true");
  await expect(scene).toHaveAttribute("focusable", "false");
  await expect(page.getByRole("status")).toHaveAttribute("aria-live", "polite");
});
