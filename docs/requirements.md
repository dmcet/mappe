# Application Crew

### What is it?
- CrewAI application to produce optimized CVs
- Focused on IT jobs in the German market

### Technical requirements
- Uses CrewAI as a multiagentic platform
- Uses a Claude API token for agentic work
- Is running in a Docker container for reproducible builds and easy deployment/shipping
- the Docker container is self-contained, hence it contains all the required tools for processing/building the intermediate steps (e.g. Python, LaTeX, Markdown processing tools, ...)
- Provides a simple, modern web UI where the process can be started and the current state of the workers can be observed
- The pipeline should be fully operable from the Web UI, including the Download of intermediates/end results
- Performs as much of the work in Python, only uses Claude for reasoning workloads, everything deterministic should be performed in Python using suitable algorithms
- The models sent to the AI should be as simple as possible, avoid complex schemas

### Input/Output
- Inputs:
  - a link to a job listing, or a list of links
  - a CV in Markdown format of the candidate that needs to be applied
  - the web UI allows to remember CVs, hence you can use the same CV to apply to multiple positions at different points in time
  - a list of requirements to check the listing against, e.g. desired benefits, job location, remote work possibilities, salary range if available
  - the documents should be in English or German, depending on the requirements of the listing.
- Outputs:
  - all the required documents which are needed for the application (cover letter, adapted CV, ...) in PDF format
  - those documents are either generated via LaTeX or some Markdown-based process
  - modern, clear to read templates are used. These templates must come from open sources.
  - the intermediates and the end results should all be downloadable from the Web UI

### Workflow
The whole workflow happens via the Web UI. Everything is facts-based, nothing is made up.

1. The CV is processed and brought into an internal format (JSON) (Parser Agent)
   - this internal format contains at least the following information:
     - applicant name
     - applicant address
     - spoken languages
     - skills (soft skills, programming languages, etc.)
     - certifications
     - education
     - position information (company, role, responsibilities, used technologies)
   - if any of the information is missing, the user is warned and prompted to add it
   - the user can choose to start anyway if the information is not available to him/if some fields are not applicable
   - before continuing, the Web UI shows what information it extracted and shows a summary to the user
   - if the user continues, the workflow continues
2. The job position is parsed (Parser Agent)
   - this is, again, brought into an internal format, which includes
     - responsibilities
     - required skills,
     - nice to have skills,
     - company name,
     - if given: company domain (automotive, banking, insurance, medical, ...)
     - location (or remote),
     - if hybrid: onsite days per week
     - if given: salary band
     - if mentioned: benefits
   - this always happens as a best guess, if something is not present that's okay
3. The skills of the applicant are compared to the position (Matcher Agent)
   - a verdict is given: does it make sense to apply for this position or not?
   - this verdict is based on hard facts (years of experience, relevant technical skills etc.)
   - it is also taken into consideration whether similar skills are present which can justify using the applicant in this position (e.g. applicant has worked in Android for a long time, but it's Java/Kotlin position with Spring Boot -> applicant can learn those skills on the job)
   - in any case, after this step, the rationale for/against an application is given to the applicant
   - he can decide whether to proceed with the application or not
   - the matcher agent highlights focus points for the next agent in the chain which need to be highlighted for the position at hand
   - the matcher agent passes the candidates' full information along with its list of highlight points to the CV author
4. A tailored CV is written for this position in Markdown/LaTeX, depending on the template we will use, will be decided on later (Author agent)
   - It must contain the following information and be ATS-friendly
      - [ ] Contact details: Include your name, phone number, email and city.
      - [ ] Optional profile: Write 2–3 sentences stating your target role, years of experience and strongest relevant skills.
      - [ ] Job-specific keywords: Identify the tools, skills and qualifications in the advertisement. Use matching terms where they accurately describe your experience.
      - [ ] Evidence for skills: Include relevant keywords naturally in your work experience, alongside examples of applying them.
      - [ ] Complete employment details: Give each position its job title, employer, location and employment dates.
      - [ ] Relevant responsibilities and achievements: Include 3–5 bullets per role, prioritizing what matters for the target position.
      - [ ] Measurable results: Quantify achievements where possible.
      - [ ] Education: Include your qualification, institution, location and dates.
      - [ ] Skills: Name relevant technical tools and professional competencies explicitly.
      - [ ] Languages: State each language and proficiency level.
      - [ ] Certifications: Include the full name, abbreviation, issuing organization and year.
      - [ ] Additional experience: Include projects, publications or volunteering when relevant.
      - [ ] Final relevance check: Remove irrelevant details, clichés and unnecessary repetition. Avoid keyword stuffing.
   - The author agent makes sure to produce valid Markdown/LaTeX
   - If required by the position, the author agent also produces a cover letter
5. The CV/application letter is checked by an ATS-simulating agent (ATS Agent)
   - The agent gives a verdict whether the CV would pass the ATS step
   - If it would not pass it, the CV goes back to the author agent for it to perform the rework
   - this loop continues until the ATS agent would accept the CV
   - this loop continues for max. 20 iterations
6. The now ATS-hardened CV/application letter goes to an recruiter agent (Recruiter agent)
   - This agent simulates a standard tech-recruiter
   - The criterion here is whether the recruiter would invite the applicant to a first round
   - Same loop as with the ATS: the CV is modified as often as required so that the Recruiter agent
   - Again, 20 loops max.
7. The documents are compiled/rendered to PDF and set to the side for the user to download and send (Logistics agent)
   - This agent verifies the technical validity of the LaTeX/Markdown document and fixes minor syntax errors or such
   - It performs all the tool calls, cleans up the document names and puts the PDFs into a download space so that the user can download them from the Web UI
8. The user downloads everything and sends out the application