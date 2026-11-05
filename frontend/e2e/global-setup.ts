import type { FullConfig } from "@playwright/test";

/** Refuse to run against a server that isn't in demo mode: the tests create CVs and runs,
 *  and outside demo mode those would land in real data and call the Claude API. */
export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0].use.baseURL;
  let health: { demo?: boolean; frontend?: boolean };
  try {
    health = await (await fetch(`${baseURL}/health`)).json();
  } catch (err) {
    throw new Error(`No Mappe server at ${baseURL} (${err}). Start one in demo mode first.`);
  }
  if (!health.demo) throw new Error(`${baseURL} is not in demo mode (APP_DEMO=1); refusing to run.`);
  if (!health.frontend) throw new Error(`${baseURL} serves no frontend build.`);
}
