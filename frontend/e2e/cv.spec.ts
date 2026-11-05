import { expect, test } from "@playwright/test";
import { addConfirmedCv, unique } from "./helpers";

test("add a CV, check the extraction and confirm it", async ({ page }) => {
  const label = unique("E2E CV");
  await addConfirmedCv(page, label);

  await expect(page.getByRole("heading", { level: 1 })).toContainText(label);
  await expect(page.getByText("Experience", { exact: true })).toBeVisible();
  await expect(page.getByText("Other roles to consider")).toBeVisible();

  await page.locator(".topbar__nav").getByRole("link", { name: "CVs" }).click();
  await expect(page.locator(".run-card", { hasText: label })).toBeVisible();
});

test("delete a CV", async ({ page }) => {
  const label = unique("E2E delete");
  await addConfirmedCv(page, label);
  await page.getByRole("button", { name: "Delete CV" }).click();
  await page.getByRole("dialog").getByRole("button", { name: /Delete/ }).click();
  await expect(page).toHaveURL(/\/cvs$/);
  await expect(page.locator(".run-card", { hasText: label })).toHaveCount(0);
});
