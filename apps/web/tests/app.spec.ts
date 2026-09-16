import { test, expect } from "@playwright/test";

test("landing, responsive layout, and sign-in", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: /Ideas need room/ }),
  ).toBeVisible();
  await page.screenshot({ path: "test-results/landing.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("link", { name: "Create your workspace" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("link", { name: "Create your workspace" }).click();
  await expect(
    page.getByRole("button", { name: "Continue with Google" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Continue with GitHub" }),
  ).toBeVisible();
  await expect(page.getByLabel("Email address")).toBeVisible();
  expect(errors).toEqual([]);
});

test("real API workspace, creation, settings, and billing", async ({
  page,
}) => {
  await page.goto("/app");
  await expect(
    page.getByRole("heading", { name: "Room for your next idea." }),
  ).toBeVisible();
  await page.screenshot({ path: "test-results/dashboard.png", fullPage: true });
  await page
    .getByRole("button", { name: "New computer", exact: true })
    .last()
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Computer name").fill("Browser test desktop");
  await dialog.getByRole("button", { name: "Create computer" }).click();
  await expect(
    page.getByRole("heading", { name: "Making room for your ideas…" }),
  ).toBeVisible();
  await expect(page.getByLabel("Task instructions")).toBeVisible();
  await page.screenshot({ path: "test-results/workspace.png", fullPage: true });
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Anthropic API key" }),
  ).toBeVisible();
  await expect(page.getByText("you@localhost")).toBeVisible();
  await page.getByRole("button", { name: "Billing", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "A little room to grow." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Manage subscription" }).click();
  await expect(page.locator(".error-banner")).toContainText(
    "Checkout is not open yet",
  );
});

test("unconfigured trial never requests payment", async ({ page }) => {
  await page.goto("/trial");
  await expect(
    page.getByRole("heading", { name: /Your tokens/ }),
  ).toBeVisible();
  await expect(
    page.getByText("Token-holder trials are coming soon."),
  ).toBeVisible();
  await expect(page.getByText(/Do not send tokens/)).toBeVisible();
  await expect(page.getByLabel("Transaction ID")).toHaveCount(0);
  await page.screenshot({ path: "test-results/trial.png", fullPage: true });
});
