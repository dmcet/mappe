# Mappe

### What is it?
- A local, single-user web application that produces tailored, ATS-friendly application documents (CV and optional cover letter)
- Focused on IT jobs in the German market
- Architecture and technology decisions: see [architecture.md](architecture.md)

### Technical requirements
- Uses the Claude API (Anthropic Python SDK) for all reasoning workloads; the API key is passed at runtime via environment variable, never baked into the image
- Orchestration is plain Python: an explicit, persisted state machine (no agent framework). The "agents" below are pipeline steps with a dedicated prompt, not autonomous agents
- Runs in a Docker container for reproducible builds and easy deployment/shipping
- The Docker container is self-contained and contains all required tools (Python, Typst, PDF text extraction, ...)
- Local and single-user: no authentication, data stays on a mounted volume (SQLite + files)
- Provides a simple, modern web UI where the process can be started and the current state of each run can be observed live
- The pipeline is fully operable from the Web UI, including the download of intermediates/end results
- As much work as possible is done in Python; Claude is only used for reasoning workloads. Everything deterministic (fetching, language detection, date math, skill matching, requirement checks, ATS checks, rendering, file handling) is performed in Python
- The models sent to/received from the AI are as simple as possible: flat Pydantic models, lists of strings, max. 2 levels of nesting
- Runs are persisted and resumable: a run waiting for user input survives container restarts

### Input/Output
- Inputs:
  - a link to a job listing, or a list of links
    - the listing is fetched automatically via HTTP (schema.org `JobPosting` JSON-LD first, then main-text extraction)
    - if fetching fails (bot protection, login wall, JS-only page), the user pastes the listing text in the UI
  - a CV in Markdown format of the candidate
  - the web UI remembers CVs, so the same (already parsed and confirmed) CV can be reused for multiple positions at different points in time
  - a list of requirements to check the listing against (e.g. desired benefits, job location, remote work, onsite days, salary range)
    - each requirement is marked as **must-have** (failing it stops the run before any expensive step) or **nice-to-have** (influences the match score)
    - if the listing doesn't mention the information (e.g. no salary given), the requirement is treated as **unknown**, which is shown to the user and does not fail a must-have
  - the documents are written in English or German, depending on the language of the listing (detected deterministically)
- Outputs:
  - a tailored CV and, optionally, a cover letter, in PDF format
  - documents are generated via **Typst** from open-source templates
    - CV: single-column, ATS-friendly layout (e.g. based on RenderCV themes)
    - cover letter: DIN 5008 business letter layout
  - German conventions: **no photo, no date of birth, no marital status**
  - all intermediates (parsed CV, parsed listing, match report, drafts per iteration, check reports) and the end results are downloadable from the Web UI

### Workflow
The whole workflow happens via the Web UI. Everything is facts-based, nothing is made up.

Multiple links result in **separate runs**, one per listing, each with its own status and user gates. Runs are processed via a small queue (default: 2 concurrently). The run list shows the match score of each run so the user can prioritize.

1. **Parse CV** (Parser step, once per CV — reused by all runs)
   - The CV is brought into an internal format (JSON). Every fact receives a stable ID so later steps can reference it.
   - The internal format contains at least:
     - applicant name, city/address, email, phone, links (LinkedIn, GitHub, portfolio)
     - spoken languages with CEFR level (A1–C2 / native)
     - skills (soft skills, programming languages, tools, frameworks, ...)
     - certifications (full name, abbreviation, issuing organization, year)
     - education (qualification, institution, location, start/end dates)
     - positions (company, role, location, **start/end dates**, responsibilities, achievements, used technologies)
     - projects, publications, volunteering
     - optional: notice period, earliest start date, salary expectation, work permit/visa status
   - If any information is missing, the user is warned and can add it in the UI, or continue anyway (fields not available / not applicable)
   - The Web UI shows the extracted information and a summary; the user confirms before the CV can be used

2. **Fetch and parse the job listing** (Parser step)
   - Fetching and language detection are deterministic
   - The listing is brought into an internal format (best guess, missing fields are fine):
     - responsibilities
     - required skills
     - nice-to-have skills
     - company name
     - if given: company domain (automotive, banking, insurance, medical, ...)
     - location (or remote)
     - if hybrid: onsite days per week
     - if given: salary band
     - if mentioned: benefits
     - whether a cover letter is requested
   - **Must-have requirements are checked here (in Python)**. If one fails, the run stops with a short explanation; the user can override and continue.

3. **Match** (Matcher step)
   - Python pre-computes: normalized skill overlap (synonyms + ESCO taxonomy), years of experience per skill (from position dates), nice-to-have requirement results
   - Claude judges on top of this: transferable skills (e.g. long Android experience → Java/Kotlin + Spring Boot position: can learn on the job), overall fit, and gives a verdict (apply / don't apply) with a rationale and a score
   - The matcher produces a list of highlight points for the author step
   - **User gate:** the rationale is shown to the user, who decides whether to proceed. The user also decides whether a cover letter is generated (preselected if the listing requests one or the listing is German).

4. **Author** (Author step)
   - Claude writes the **content** of the tailored CV (and optional cover letter) as a simple structured model — never Typst/LaTeX/Markdown markup. Python renders the content into the templates.
   - Every bullet/claim references the IDs of the source facts it is based on
   - The CV must contain the following and be ATS-friendly:
      - [ ] Contact details: name, phone number, email and city.
      - [ ] Optional profile: 2–3 sentences stating target role, years of experience and strongest relevant skills.
      - [ ] Job-specific keywords: tools, skills and qualifications from the listing, using matching terms where they accurately describe the experience.
      - [ ] Evidence for skills: relevant keywords used naturally in the work experience, alongside examples of applying them.
      - [ ] Complete employment details: job title, employer, location and employment dates for each position.
      - [ ] Relevant responsibilities and achievements: 3–5 bullets per role, prioritizing what matters for the target position.
      - [ ] Measurable results: quantify achievements where the source CV provides numbers (never invent numbers).
      - [ ] Education: qualification, institution, location and dates.
      - [ ] Skills: relevant technical tools and professional competencies named explicitly.
      - [ ] Languages: each language and proficiency level.
      - [ ] Certifications: full name, abbreviation, issuing organization and year.
      - [ ] Additional experience: projects, publications or volunteering when relevant.
      - [ ] Final relevance check: remove irrelevant details, clichés and unnecessary repetition. Avoid keyword stuffing.

5. **Review loop** (Fact check → Render → ATS check → Recruiter review)
   - Each iteration runs, in this order:
     1. **Fact check (Python):** every bullet references valid source IDs; every number, date and skill in the output exists in the source CV. Violations go straight back to the author.
     2. **Render (Python):** content → Typst → PDF
     3. **ATS check (mostly Python, on the extracted PDF text):** parseability (reading order, contact details and section headings found), keyword coverage of required skills, checklist rules (bullets per role, dates present, keyword frequency limits). Claude only judges what Python can't (e.g. whether keywords are used naturally).
     4. **Recruiter review (Claude):** simulates a German tech recruiter and scores the CV against a fixed rubric (criteria scored 1–5). Criterion: would the applicant be invited to a first round?
   - If any check fails or the rubric score is below the threshold, the concrete feedback goes back to the author for a rework
   - **Max. 4 iterations**; stop early when all checks pass, or when the score didn't improve for 2 iterations. The best-scoring version that passes the fact check is kept.
   - All iterations (content, PDF, reports) are stored as intermediates

6. **Final review** (User gate)
   - The UI shows the final content in an editor, side by side with the source CV, with check results and warnings highlighted
   - The user can edit the text directly; edits are re-rendered and re-checked deterministically (fact check is shown as a warning, not a blocker — the user is the authority)
   - The user approves the final version

7. **Deliver** (Logistics step, deterministic)
   - Final render to PDF; if Typst compilation fails, Claude is used as a fallback to repair the document content
   - Files are named consistently (e.g. `Lastname_Firstname_CV_Company.pdf`, `Lastname_Firstname_Cover_Letter_Company.pdf`) and put into the run's download space

8. The user downloads everything and sends out the application
   - If the listing gives an email address and there is a cover letter, the application can be sent by email: the cover letter text is the email body, the CV PDF the attachment, with a greeting to the contact person named in the listing (a neutral one if none is named)
   - Mappe hands the email to the user's mail app (Apple Shortcut on a Mac, `.eml` draft elsewhere) and never sends it itself; no mail credentials are stored. Details: [email.md](email.md)

### Cost and model usage
- Default model: Claude Opus 5.5 with per-step effort levels (see architecture.md); models and effort levels are configurable per step
- Prompt caching for the stable parts of the review loop (system prompts, source CV, listing)
- Token usage and estimated cost are tracked per run and shown in the UI; an optional cost limit per run aborts the review loop gracefully
