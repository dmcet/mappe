import { render, screen } from "@testing-library/react";
import { EmailPanel, isMac } from "../pages/run/Email";
import { contactText } from "../pages/run/Details";
import type { ApplicationEmail, Listing } from "../types";

const EMAIL: ApplicationEmail = {
  available: true,
  to: "bewerbung@beispiel.de",
  subject: "Bewerbung als Python Developer",
  body: "Sehr geehrte Frau Schmidt,\n\nIhre Plattform ...",
  cv_name: "Doe_Jane_Lebenslauf_Beispiel.pdf",
  cv_url: "http://127.0.0.1:8000/api/runs/3/final/Doe_Jane_Lebenslauf_Beispiel.pdf",
  eml_url: "http://127.0.0.1:8000/api/runs/3/email.eml",
  shortcut_url: "shortcuts://run-shortcut?name=Mappe%20Mail&input=text&text=x",
};

function serve(data: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(data), { status: 200 })));
}

describe("email panel", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("offers the shortcut first on a Mac", async () => {
    serve(EMAIL);
    render(<EmailPanel runId={3} mac />);
    const links = await screen.findAllByRole("link", { name: /Apple Mail|\.eml/ });
    expect(links.map((l) => l.textContent)).toEqual(["Open in Apple Mail", "Download email (.eml)"]);
    expect(links[0].getAttribute("href")).toBe(EMAIL.available && EMAIL.shortcut_url);
    expect(screen.getByText("bewerbung@beispiel.de")).toBeInTheDocument();
    expect(screen.getByText("Doe_Jane_Lebenslauf_Beispiel.pdf")).toBeInTheDocument();
  });

  it("offers the .eml first elsewhere", async () => {
    serve(EMAIL);
    render(<EmailPanel runId={3} mac={false} />);
    const links = await screen.findAllByRole("link", { name: /Apple Mail|\.eml/ });
    expect(links[0].textContent).toBe("Download email (.eml)");
    expect(links[0].hasAttribute("download")).toBe(true); // a download must not end the live stream
    expect(screen.getByText(/Outlook or Thunderbird/)).toBeInTheDocument();
  });

  it("explains why there is no email", async () => {
    serve({ available: false, reason: "The listing gives no email address for applications." });
    render(<EmailPanel runId={3} mac />);
    expect(await screen.findByText(/no email address/)).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("detects macOS", () => {
    expect(isMac("Mozilla/5.0 (Macintosh; Intel Mac OS X 15_0)")).toBe(true);
    expect(isMac("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")).toBe(false);
    expect(isMac("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)")).toBe(false);
  });
});

describe("listing contact", () => {
  const base = { language: "de", contact_email: "a@b.de" } as Listing;
  it("shows form of address, title, name and email", () => {
    expect(
      contactText({ ...base, contact_name: "Anna Schmidt", contact_gender: "female", contact_academic_title: "Dr." }),
    ).toBe("Frau Dr. Anna Schmidt · a@b.de");
    expect(contactText({ ...base, language: "en", contact_name: "Kim Lee", contact_gender: "male" })).toBe(
      "Mr Kim Lee · a@b.de",
    );
    expect(contactText({ language: "de" } as Listing)).toBe("—");
  });
});
