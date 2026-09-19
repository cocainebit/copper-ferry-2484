import { expect, test, type Page } from "@playwright/test";

// The runtime strip in every billing state it can be in. The API is real; only the runtime
// endpoint is replaced, because no tier is priced in the test environment and the metered
// states would otherwise never render.
const base = {
  billing: "platform",
  seconds_left: 0,
  cap_hours: 190,
  used_this_window_seconds: 0,
  window_days: 30,
  capped: false,
  covered_by_pass: false,
  price_micro_usdc_per_hour: 100_000,
  free: false,
  price_unavailable: false,
  due: null,
  packs: [],
};
const due = {
  id: "pack-due",
  hours: 1,
  status: "open",
  pay_url: "http://127.0.0.1:8760/pay/chg_1",
  amount_micro_usdc: 100_000,
};

async function openComputer(page: Page, runtime: { current: object }) {
  await page.clock.install();
  await page.route("**/api/v1/computers/*/runtime", (route) =>
    route.fulfill({ json: runtime.current }),
  );
  await page.goto("/app");
  await page
    .getByRole("button", { name: "New computer", exact: true })
    .last()
    .click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Computer name").fill("Metered desktop");
  await dialog.getByRole("button", { name: "Create computer" }).click();
  await expect(
    page.getByRole("heading", { name: "Your computer is taking a breather." }),
  ).toBeVisible();
}

async function show(page: Page, runtime: { current: object }, state: object) {
  runtime.current = { ...base, ...state };
  await page.clock.fastForward(16_000); // the strip refreshes every 15 seconds
}

test("runtime strip states: metered, due, capped, free, pass, unavailable", async ({
  page,
}) => {
  const runtime = {
    current: {
      ...base,
      seconds_left: 4 * 3600 + 12 * 60,
      used_this_window_seconds: 42.3 * 3600,
    } as object,
  };
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    // The e2e stack runs no desktop worker, so the automatic start after creation is refused
    // with a 503 by design. Every other error, including the strip's own, fails the test.
    if (message.location().url.includes("/actions/start")) return;
    consoleErrors.push(`${message.text()} (${message.location().url})`);
  });
  await openComputer(page, runtime);
  const strip = page.locator(".runtime-strip");

  await expect(strip).toContainText("4 h 12 min of paid runtime left");
  await expect(strip).toContainText("42.3 of 190 h this month");
  await expect(strip.getByRole("meter")).toHaveAttribute(
    "aria-valuenow",
    "42.3",
  );
  const add = strip.getByRole("group", { name: "Add paid runtime" });
  await expect(add.getByRole("button")).toHaveText(["1 h", "10 h", "190 h"]);
  await expect(add.getByRole("button", { name: "10 h" })).toHaveAttribute(
    "title",
    /10 h for 1\.00 USDC/,
  );
  await strip.screenshot({ path: "test-results/runtime-metered.png" });

  // Buying sends the pack size, and nothing else decides it.
  let bought: unknown = null;
  await page.route("**/api/v1/computers/*/runtime/hours", async (route) => {
    bought = route.request().postDataJSON();
    await route.fulfill({ status: 201, json: { ...due, hours: 10 } });
  });
  await add.getByRole("button", { name: "10 h" }).click();
  await expect.poll(() => bought).toEqual({ hours: 10 });

  await show(page, runtime, { seconds_left: 180, due });
  await expect(strip).toHaveClass(/due/);
  await expect(strip).toContainText("3 min of paid runtime left");
  const pay = strip.getByRole("link", { name: /Pay 0\.10 USDC for 1 h/ });
  await expect(pay).toHaveAttribute("href", due.pay_url);
  await expect(add).toHaveCount(0); // one way to pay at a time
  await strip.screenshot({ path: "test-results/runtime-due.png" });

  await show(page, runtime, { seconds_left: 0, due });
  await expect(strip).toContainText("No paid runtime");
  await expect(strip).toContainText("0 of 190 h this month");
  await expect(pay).toBeVisible();

  await show(page, runtime, {
    capped: true,
    seconds_left: 0,
    used_this_window_seconds: 190 * 3600,
  });
  await expect(strip).toContainText(
    "Monthly cap reached. Free for the rest of this 30-day window",
  );
  await expect(strip).toContainText("190 of 190 h this month");
  await expect(add).toHaveCount(0);
  await strip.screenshot({ path: "test-results/runtime-capped.png" });

  await show(page, runtime, { free: true, price_micro_usdc_per_hour: null });
  await expect(strip).toContainText("Runtime is free on this size");
  await expect(strip.getByRole("meter")).toHaveCount(0);
  await expect(add).toHaveCount(0);

  await show(page, runtime, { covered_by_pass: true });
  await expect(strip).toContainText("Covered by your pass");
  await expect(add).toHaveCount(0);

  await show(page, runtime, { price_unavailable: true });
  await expect(strip).toContainText("Runtime prices are unavailable right now");
  await expect(add).toHaveCount(0);

  // In context, then at phone width: it may wrap, but it must never scroll sideways.
  await show(page, runtime, {
    seconds_left: 4 * 3600 + 12 * 60,
    used_this_window_seconds: 42.3 * 3600,
  });
  await page.screenshot({ path: "test-results/runtime-in-context.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(strip).toContainText("4 h 12 min of paid runtime left");
  const overflow = await strip.evaluate(
    (el) => el.scrollWidth - el.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  await strip.screenshot({ path: "test-results/runtime-narrow.png" });
  await page.setViewportSize({ width: 1440, height: 1000 });

  await show(page, runtime, { billing: "credits" });
  await expect(strip).toHaveCount(0); // credits billing has its own meter
  expect(consoleErrors).toEqual([]);
});
