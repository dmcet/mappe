import { render, screen } from "@testing-library/react";
import { ListingPanel, listingUrl } from "../pages/run/Details";
import type { RunDetail } from "../types";

const listing = {
  title: "Softwarearchitekt (m/w/d)",
  company: "SINTEC Informatik GmbH",
  domain: null,
  language: "de",
  responsibilities: [],
  required_skills: [],
  nice_to_have_skills: [],
  qualifications: [],
  location: "Fürth",
  remote: "hybrid",
  onsite_days_per_week: null,
  salary_min: null,
  salary_max: null,
  salary_currency: null,
  salary_period: null,
  benefits: [],
  cover_letter_requested: false,
};

const run = (over: { listing_url?: string | null; final_url?: string }) =>
  ({
    listing_url: over.listing_url ?? null,
    state: {
      listing,
      fetch: over.final_url ? { job_posting: null, language: "de", final_url: over.final_url } : null,
    },
  }) as unknown as RunDetail;

describe("listing panel", () => {
  it("links to the original listing", () => {
    render(<ListingPanel run={run({ listing_url: "https://www.example.com/jobs/123?utm=x" })} />);
    expect(screen.getByText("Open listing ↗")).toHaveAttribute("href", "https://www.example.com/jobs/123?utm=x");
    expect(screen.getByText("example.com")).toHaveAttribute("href", "https://www.example.com/jobs/123?utm=x");
  });

  it("prefers the page the fetch ended up on", () => {
    expect(listingUrl(run({ listing_url: "https://a.example/x", final_url: "https://b.example/y" }))).toBe(
      "https://b.example/y",
    );
  });

  it("says when the listing was pasted", () => {
    render(<ListingPanel run={run({})} />);
    expect(screen.getByText("pasted text")).toBeInTheDocument();
    expect(screen.queryByText("Open listing ↗")).not.toBeInTheDocument();
  });
});
