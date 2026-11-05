import { expect, type Page } from "@playwright/test";

export const SAMPLE_CV = `# Erika Mustermann
erika@example.com · +49 170 1234567 · Berlin

## Erfahrung
### Senior Backend Engineer, Beispiel GmbH (2020 – heute)
- Python-Services mit FastAPI entwickelt
`;

export const SAMPLE_LISTING = `Backend Engineer (m/w/d) bei Beispiel AG, Berlin.
Wir suchen Verstärkung mit Python, FastAPI und PostgreSQL.`;

/** A unique label, so tests don't depend on what earlier tests left in the database. */
export const unique = (prefix: string) => `${prefix} ${Date.now().toString(36)}`;

/** Add a CV through the UI and confirm it; ends on the CV page. */
export async function addConfirmedCv(page: Page, label: string) {
  await page.goto("/cvs");
  await page.getByLabel("Label").fill(label);
  await page.getByLabel("CV (Markdown)").fill(SAMPLE_CV);
  await page.getByRole("button", { name: "Parse CV" }).click();
  await expect(page).toHaveURL(/\/cvs\/\d+$/);
  await page.getByRole("button", { name: /^Confirm CV/ }).click();
  await expect(page.getByRole("button", { name: /^Confirm CV/ })).toBeHidden();
}

/** The CV picker of "New application" (its accessible name includes the chosen option). */
export const cvSelect = (page: Page) => page.locator("label").filter({ hasText: /^CV/ }).locator("select");
