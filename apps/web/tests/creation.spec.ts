import { test, expect } from "@playwright/test";
test("template creation starts with template resources and waits for copy completion", async ({
  page,
}) => {
  let submitted: unknown;
  let startRequests = 0;
  let copied = false;
  const computer = {
    id: "template-target",
    workspace_id: "local-workspace",
    name: "From template",
    status: "copying",
    controller: "human",
    error: null,
  };
  await page.route("**/api/v1/workspaces/*/templates", (route) =>
    route.fulfill({
      json: [
        {
          id: "ready-template",
          name: "Browser tools",
          status: "ready",
          cpu: 1,
          memory_gib: 2,
          resolution: "1280x720",
          idle_timeout_minutes: 0,
        },
        {
          id: "pending-template",
          name: "Not ready",
          status: "creating",
          cpu: 2,
          memory_gib: 4,
        },
      ],
    }),
  );
  await page.route("**/api/v1/workspaces/*/computers", async (route) => {
    if (copied) return route.fulfill({ json: [computer] });
    return route.continue();
  });
  await page.route(
    "**/api/v1/templates/ready-template/computers",
    async (route) => {
      submitted = route.request().postDataJSON();
      copied = true;
      return route.fulfill({
        json: { target_id: computer.id, status: "queued" },
      });
    },
  );
  await page.route(
    "**/api/v1/computers/template-target/actions/start",
    (route) => {
      startRequests++;
      return route.fulfill({ json: {} });
    },
  );
  await page.route("**/api/v1/computers/template-target/events", (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route("**/api/v1/computers/template-target/runs", (route) =>
    route.fulfill({ json: [] }),
  );
  await page.goto("/app");
  await page
    .getByRole("button", { name: "New computer", exact: true })
    .last()
    .click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("Starting environment")
    .selectOption("ready-template");
  await expect(
    dialog.getByLabel("Starting environment").locator("option"),
  ).toHaveCount(2);
  await expect(dialog.getByLabel("CPU", { exact: true })).toHaveValue("1");
  await expect(dialog.getByLabel("Memory", { exact: true })).toHaveValue("2");
  await expect(dialog.getByLabel("Display resolution")).toHaveValue("1280x720");
  await dialog.getByLabel("Display resolution").selectOption("1920x1080");
  await expect(dialog.getByLabel("Idle stop")).toHaveValue("0");
  await dialog.getByLabel("Memory", { exact: true }).selectOption("4");
  await dialog.getByLabel("Computer name").fill("From template");
  await dialog.getByRole("button", { name: "Create computer" }).click();
  await expect(
    page.getByRole("heading", { name: "Preparing your template…" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Start", exact: true }),
  ).toBeDisabled();
  expect(submitted).toEqual({
    name: "From template",
    cpu: 1,
    memory_gib: 4,
    resolution: "1920x1080",
    idle_timeout_minutes: 0,
  });
  expect(startRequests).toBe(0);
});
test("template load failures preserve clean creation and show API creation errors in dialog", async ({
  page,
}) => {
  await page.route("**/api/v1/workspaces/*/templates", (route) =>
    route.fulfill({ status: 503, json: { detail: "Try again later" } }),
  );
  await page.route("**/api/v1/workspaces/*/computers", (route) =>
    route.request().method() === "POST"
      ? route.fulfill({
          status: 409,
          json: { detail: "Saved computer limit reached" },
        })
      : route.continue(),
  );
  await page.goto("/app");
  await page
    .getByRole("button", { name: "New computer", exact: true })
    .last()
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText(/Templates unavailable/)).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "Create computer" }),
  ).toBeEnabled();
  await dialog.getByRole("button", { name: "Create computer" }).click();
  await expect(dialog.getByRole("alert")).toContainText(
    "Saved computer limit reached",
  );
  await expect(
    dialog.getByRole("button", { name: "Create computer" }),
  ).toBeEnabled();
});
