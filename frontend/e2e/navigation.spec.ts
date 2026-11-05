import { expect, test } from "@playwright/test";

test("demo banner and every page in the top navigation", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Demo mode: Claude is not called")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Applications" })).toBeVisible();

  const nav = page.locator(".topbar__nav");
  for (const [link, heading, url] of [
    ["Find jobs", "Find jobs", /\/search$/],
    ["CVs", "CVs", /\/cvs$/],
    ["Costs", "Model costs", /\/costs$/],
    ["Applications", "Applications", /\/$/],
  ] as const) {
    await nav.getByRole("link", { name: link }).click();
    await expect(page).toHaveURL(url);
    await expect(page.getByRole("heading", { level: 1 })).toContainText(heading);
  }
});

test("deep links are served by the app and unknown routes say so", async ({ page }) => {
  await page.goto("/costs");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Model costs");
  await page.goto("/no/such/page");
  await expect(page.getByText("Page not found.")).toBeVisible();
});
