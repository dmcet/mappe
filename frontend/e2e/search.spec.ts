import { expect, test } from "@playwright/test";
import { addConfirmedCv, cvSelect, unique } from "./helpers";

test("job search ranks the recorded sample listings", async ({ page }) => {
  test.setTimeout(150_000);
  const label = unique("E2E search");
  await addConfirmedCv(page, label);
  await page.locator(".topbar__nav").getByRole("link", { name: "Find jobs" }).click();
  await expect(page.getByText("No AI costs")).toBeVisible();

  await cvSelect(page).selectOption({ label });
  // Titles come from the CV as chips; search for one only.
  const chips = page.locator(".chip__toggle[aria-pressed=true]");
  await expect(chips.first()).toBeVisible();
  await page.getByLabel("Add a job title").fill("Backend Engineer");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const others = chips.filter({ hasNotText: /^Backend Engineer$/ });
  while ((await others.count()) > 0) await others.first().click();
  await expect(chips).toHaveCount(1);
  await page.getByRole("button", { name: "Search", exact: true }).click();

  // The first search reads the sample listings with the local embedding model.
  const hits = page.locator(".hit");
  await expect(hits.first()).toBeVisible({ timeout: 120_000 });
  await expect(hits.first().locator(".hit__score")).toHaveText(/\d+/);

  const pdf = page.waitForEvent("download");
  await page.getByRole("link", { name: "Export list (PDF)" }).click();
  expect((await pdf).suggestedFilename()).toMatch(/\.pdf$/);
});
