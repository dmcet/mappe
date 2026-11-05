import { expect, test } from "@playwright/test";
import { addConfirmedCv, cvSelect, SAMPLE_LISTING, unique } from "./helpers";

test("from a pasted listing to the final PDFs", async ({ page }) => {
  test.setTimeout(180_000);
  const label = unique("E2E apply");
  await addConfirmedCv(page, label);

  await page.locator(".topbar__nav").getByRole("link", { name: "Applications" }).click();
  await cvSelect(page).selectOption({ label });
  await page.getByLabel("…or paste a listing").fill(SAMPLE_LISTING);
  await page.getByRole("button", { name: "Start" }).click();
  await expect(page).toHaveURL(/\/runs\/\d+$/);

  // Gate 1: the assessment waits for the decision.
  const apply = page.getByRole("button", { name: "Apply", exact: true });
  await expect(apply).toBeVisible({ timeout: 60_000 });
  await page.getByLabel("also write a cover letter").check();
  await apply.click();
  await expect(page.getByText("You decided to apply with a cover letter.")).toBeVisible();

  // Review loop runs on its own (writing, fact check, rendering, claims, ATS, recruiter).
  const approve = page.getByRole("button", { name: "Approve and finish" });
  await expect(approve).toBeVisible({ timeout: 120_000 });
  await expect(page.getByRole("link", { name: "CV PDF" })).toBeVisible();

  const draft = page.waitForEvent("download");
  await page.getByRole("link", { name: "CV PDF" }).click();
  expect((await draft).suggestedFilename()).toMatch(/\.pdf$/);

  // Gate 2: final review.
  await approve.click();
  await expect(page.getByRole("heading", { name: "Ready to send" })).toBeVisible({ timeout: 60_000 });
  // Final files are named after the candidate and the company (German listing: Lebenslauf).
  await expect(page.getByRole("link", { name: /_Lebenslauf_.+\.pdf$/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /_Anschreiben_.+\.pdf$/ })).toBeVisible();
  const zip = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download everything as ZIP" }).click();
  expect((await zip).suggestedFilename()).toMatch(/\.zip$/);

  // Demo mode never costs anything.
  await expect(page.getByRole("link", { name: /today \$0\.00/ })).toBeVisible();
});

test("decline an application at the decision gate", async ({ page }) => {
  test.setTimeout(120_000);
  const label = unique("E2E decline");
  await addConfirmedCv(page, label);
  await page.locator(".topbar__nav").getByRole("link", { name: "Applications" }).click();
  await cvSelect(page).selectOption({ label });
  await page.getByLabel("…or paste a listing").fill(SAMPLE_LISTING);
  await page.getByRole("button", { name: "Start" }).click();

  const decline = page.getByRole("button", { name: "Don't apply" });
  await expect(decline).toBeVisible({ timeout: 60_000 });
  await decline.click();
  await expect(page.getByRole("button", { name: "Apply", exact: true })).toBeHidden();
});
