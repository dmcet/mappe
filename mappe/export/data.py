"""Build the data for the export template (``typst/export.typ``).

Everything is formatted here, in Python; the template only lays it out. Labels follow the
UI. The texts are neutral ("the candidate"), because the export is read by someone else.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mappe.config import Settings
from mappe.db import Run
from mappe.domain.models import ParsedCV, ParsedListing
from mappe.runner.engine import run_title
from mappe.search.models import JobHit
from mappe.search.sources import SOURCES
from mappe.steps.final import delivery_names, file_part

DOC_SCHEME = "mappe://doc/"  # links to the documents next to the report; rewritten to files

VERDICTS = {"apply": "Apply", "consider": "Consider applying", "dont_apply": "Don't apply"}
HIDDEN_LABELS = {
    "requirements": "fails a must-have",
    "elsewhere": "outside the area",
    "low_score": "low match",
    "dismissed": "dismissed",
}
STATUS_LABELS = {
    "created": "Queued",
    "fetching_listing": "Fetching listing",
    "waiting_for_listing_text": "Needs the listing text",
    "parsing_listing": "Reading listing",
    "checking_requirements": "Checking requirements",
    "stopped_by_requirements": "Must-have not met",
    "matching": "Assessing fit",
    "waiting_for_apply_decision": "Waiting for the apply decision",
    "declined": "Declined",
    "authoring": "Writing",
    "reviewing": "Reviewing",
    "waiting_for_final_review": "Documents in final review",
    "delivering": "Delivering",
    "done": "Ready to send",
    "failed": "Failed",
}
REQUIREMENT_KINDS = {
    "salary_min": "Minimum salary",
    "max_onsite_days": "Max. onsite days",
    "remote": "Fully remote",
    "location": "Cities",
    "benefit": "Benefit",
    "other": "Other",
}
CRITERIA = ["relevance", "keywords", "evidence", "clarity", "seniority"]


def tone(status: str) -> str:
    """Colour of a status, as in the UI: good | bad | you | muted | busy."""
    if status == "failed":
        return "bad"
    if status == "done":
        return "good"
    if status == "declined":
        return "muted"
    if status.startswith("waiting") or status == "stopped_by_requirements":
        return "you"
    return "busy"


def long_date(value: date | datetime) -> str:
    return f"{value.day} {value.strftime('%B')} {value.year}"


def host(url: str | None) -> str:
    if not url:
        return ""
    return (urlparse(url).hostname or url).removeprefix("www.")


def excerpt(text: str, limit: int = 600) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",.;:-") + " …"


def _thousands(n: int) -> str:
    return f"{round(n / 1000)}k" if n >= 1000 else str(n)


def salary(low: int | None, high: int | None, currency: str | None, period: str | None) -> str:
    low, high = low or high, high or low
    if low is None or high is None:
        return ""
    amount = _thousands(low) if low == high else f"{_thousands(low)}–{_thousands(high)}"
    return f"{amount} {currency or ''} / {period or 'year'}".replace("  ", " ")


def work_mode(remote: str | None, onsite_days: int | None) -> str:
    if remote == "remote":
        return "Remote"
    if remote == "hybrid":
        return f"Hybrid · {onsite_days} day(s) onsite" if onsite_days is not None else "Hybrid"
    if remote == "onsite":
        return "Onsite"
    return ""


def percent(value: float | None) -> str:
    return "" if value is None else f"{round(value * 100)}%"


def requirement_line(req: dict) -> dict:
    kind, value = req.get("kind", "other"), str(req.get("value", ""))
    if kind == "salary_min" and value.isdigit():
        value = f"{int(value):,} EUR / year"
    elif kind == "max_onsite_days":
        value = "remote only" if value == "0" else f"{value} per week"
    return {
        "label": REQUIREMENT_KINDS.get(kind, kind),
        "value": value,
        "must": req.get("must_have"),
    }


# --- documents of an application -----------------------------------------------------------


@dataclass
class Document:
    run_id: int
    kind: str  # "cv" | "letter"
    label: str  # "Tailored CV" | "Cover letter"
    name: str  # file name, as delivered
    path: Path
    final: bool  # approved and delivered, or the current draft
    file: str = ""  # path in the export archive, next to the report (see place_documents)

    @property
    def link(self) -> str:
        return f"{DOC_SCHEME}{self.run_id}/{self.kind}"


def run_documents(settings: Settings, run: Run) -> list[Document]:
    """The delivered PDFs, or else the PDFs of the current final draft."""
    state = run.state or {}
    run_dir = settings.runs_dir / str(run.id)
    labels = {"cv.pdf": ("cv", "Tailored CV"), "cover-letter.pdf": ("letter", "Cover letter")}
    docs = []
    delivery = state.get("delivery")
    if delivery:
        for name, original in delivery.get("files", {}).items():
            if original in labels:
                kind, label = labels[original]
                docs.append(Document(run.id, kind, label, name, run_dir / "final" / name, True))
    elif state.get("drafts") and state.get("cv") and state.get("listing"):
        drafts = state["drafts"]
        wanted = state.get("final_draft", drafts[-1]["iteration"])
        draft = next((d for d in drafts if d["iteration"] == wanted), drafts[-1])
        folder = run_dir / f"draft-{draft['iteration']}"
        # Named like the delivered files, marked as a draft.
        names = delivery_names(
            ParsedCV.model_validate(state["cv"]),
            ParsedListing.model_validate(state["listing"]),
            draft["lang"],
        )
        for original, (kind, label) in labels.items():
            if original in draft.get("files", {}):
                path = folder / draft["files"][original]
                name = names[original].removesuffix(".pdf") + f"_draft-{draft['iteration']}.pdf"
                docs.append(Document(run.id, kind, label, name, path, False))
    return [d for d in docs if d.path.is_file()]


def place_documents(per_run: list[tuple[Run, list[Document]]]) -> None:
    """Set each document's path in the archive: next to the report for one application,
    else in one numbered folder per application ("01_Acme_GmbH/...")."""
    with_docs = [(run, docs) for run, docs in per_run if docs]
    for n, (run, docs) in enumerate(with_docs, 1):
        company = ((run.state or {}).get("listing") or {}).get("company") or run_title(run)
        folder = "" if len(with_docs) == 1 else f"{n:02d}_{file_part(company)}/"
        for doc in docs:
            doc.file = folder + doc.name


# --- applications ----------------------------------------------------------------------------


def _fact_sources(cv: ParsedCV | None) -> dict[str, str]:
    """Fact ID -> where it comes from in the CV ("Senior Engineer · Acme")."""
    if cv is None:
        return {}
    out = {}
    for p in cv.positions:
        out[p.id] = f"{p.role} · {p.company}"
        for f in p.responsibilities + p.achievements:
            out[f.id] = out[p.id]
    for e in cv.education:
        out[e.id] = f"{e.qualification}, {e.institution}"
    for c in cv.certifications:
        out[c.id] = c.name
    for f in cv.projects:
        out[f.id] = "Projects"
    for f in cv.publications:
        out[f.id] = "Publications"
    for f in cv.volunteering:
        out[f.id] = "Volunteering"
    return out


def _cited(ids: list[str], sources: dict[str, str]) -> str:
    return " · ".join(dict.fromkeys(sources[i] for i in ids if i in sources))


def _review(state: dict) -> dict | None:
    drafts = state.get("drafts") or []
    if not drafts:
        return None
    wanted = state.get("final_draft", drafts[-1]["iteration"])
    d = next((x for x in drafts if x["iteration"] == wanted), drafts[-1])
    violations = d["cv_report"]["violations"] + d["letter_report"]["violations"]
    claims = d.get("claims") or []
    checks = [
        {
            "name": "Fact check",
            "outcome": f"{len(violations)} problem(s)" if violations else "passed",
            "tone": "bad" if violations else "good",
            "detail": "; ".join(violations)
            or "Every statement cites the CV; numbers and skills come from it.",
        }
    ]
    if d.get("source") == "user":
        checks.append(
            {
                "name": "Claims check",
                "outcome": "not run",
                "tone": "neutral",
                "detail": "Edited by hand in the final review; not re-checked by AI.",
            }
        )
    elif not violations:
        checks.append(
            {
                "name": "Claims check",
                "outcome": f"{len(claims)} problem(s)" if claims else "passed",
                "tone": "bad" if claims else "good",
                "detail": "; ".join(f"{c['kind']}: {c['explanation']}" for c in claims)
                or "No embellishments found.",
            }
        )
    ats = d.get("ats")
    if ats:
        total = len(ats["keywords_found"]) + len(ats["keywords_missing"])
        missing = ats["keywords_missing"]
        checks.append(
            {
                "name": "ATS",
                "outcome": f"{round(ats['coverage'] * 100)}% keywords",
                "tone": "good" if ats["passed"] else "bad",
                "detail": f"{len(ats['keywords_found'])} of {total} required skills the "
                "candidate has are visible in the PDF."
                + (f" Missing: {', '.join(missing)}." if missing else "")
                + "".join(f" {p}" for p in ats.get("parse_problems", [])),
            }
        )
    rec = d.get("recruiter")
    recruiter = None
    if rec:
        scores = [{"name": c, "value": rec[c]} for c in CRITERIA]
        if d.get("letter") and rec.get("cover_letter"):
            scores.append({"name": "cover letter", "value": rec["cover_letter"]})
        recruiter = {
            "average": f"{rec['average']:.1f}",
            "invite": bool(rec.get("invite")),
            "summary": rec.get("summary", ""),
            "scores": scores,
            "feedback": rec.get("feedback", []),
        }
    return {
        "drafts": len(drafts),
        "final": d["iteration"],
        "edited": d.get("source") == "user",
        "stop_reason": state.get("review_stop_reason") or "",
        "checks": checks,
        "recruiter": recruiter,
    }


def application_data(run: Run, documents: list[Document], links: bool) -> dict[str, Any]:
    """One application with its reasoning. ``links``: the documents are in the archive."""
    state = run.state or {}
    cv = ParsedCV.model_validate(state["cv"]) if state.get("cv") else None
    sources = _fact_sources(cv)
    listing = state.get("listing") or {}
    match = state.get("match")
    status = str(run.status)
    url = (state.get("fetch") or {}).get("final_url") or run.listing_url
    out: dict[str, Any] = {
        "anchor": f"run-{run.id}",
        "title": listing.get("title") or run_title(run),
        "company": listing.get("company") or "",
        "url": url or "",
        "host": host(url) or "pasted listing",
        "status": STATUS_LABELS.get(status, status),
        "tone": tone(status),
        "verdict": None,
        "listing": None,
        "requirements": [],
        "coverage": None,
        "review": None,
        "decision": "",
        "documents": [],
    }
    if listing:
        out["listing"] = {
            "location": listing.get("location") or "—",
            "work": work_mode(listing.get("remote"), listing.get("onsite_days_per_week")) or "—",
            "salary": salary(
                listing.get("salary_min"),
                listing.get("salary_max"),
                listing.get("salary_currency"),
                listing.get("salary_period"),
            )
            or "not stated",
            "language": "German" if listing.get("language") == "de" else "English",
            "required": listing.get("required_skills", []),
            "nice": listing.get("nice_to_have_skills", []),
            "benefits": listing.get("benefits", []),
            "responsibilities": listing.get("responsibilities", []),
        }
    if match:
        out["verdict"] = {
            "key": match["verdict"],
            "label": VERDICTS.get(match["verdict"], match["verdict"]),
            "score": match["score"],
            "rationale": match.get("rationale", ""),
            "strengths": [
                {"text": s["point"], "from": _cited(s["fact_ids"], sources)}
                for s in match.get("strengths", [])
            ],
            "transferable": [
                {
                    "missing": t["missing"],
                    "text": t["related_experience"],
                    "from": _cited(t["fact_ids"], sources),
                }
                for t in match.get("transferable", [])
            ],
            "gaps": match.get("gaps", []),
            "highlights": [
                {"text": h["point"], "from": _cited(h["fact_ids"], sources)}
                for h in match.get("highlights", [])
            ],
        }
    for r in state.get("requirement_results") or []:
        out["requirements"].append(
            requirement_line(r["requirement"])
            | {
                "outcome": r["outcome"],
                "tone": {"passed": "good", "failed": "bad"}.get(r["outcome"], "neutral"),
                "note": r.get("note", ""),
                "evidence": r.get("evidence") or "",
            }
        )
    analysis = state.get("analysis")
    if analysis:
        years = f"{analysis['total_years']:g} years of experience"
        if analysis.get("student_years"):
            years += f" (including {analysis['student_years']:g} as working student)"
        if analysis.get("years_required"):
            years += f" · the listing asks for {analysis['years_required']}+ years"
        out["coverage"] = {
            "summary": f"{analysis['required_matched']} matched · "
            f"{analysis['required_related']} related · of {analysis['required_total']} required",
            "years": years,
            "rows": [
                {
                    "skill": c["skill"],
                    "required": c["required"],
                    "coverage": c["coverage"],
                    "tone": {"match": "good", "missing": "bad"}.get(c["coverage"], "neutral"),
                    "cv_skill": (c.get("cv_skill") or c.get("note") or "—")
                    + (f" ({c['level']})" if c.get("level") else ""),
                    "years": f"{c['years']:g}" if c.get("years") else "",
                }
                for c in analysis["coverage"]
            ],
        }
    out["review"] = _review(state)
    decision = state.get("decision")
    if decision is not None:
        out["decision"] = "Applied" + (" with a cover letter" if decision["cover_letter"] else "")
    elif status == "declined":
        out["decision"] = "Declined"
    out["documents"] = [
        {
            "label": d.label,
            "file": d.file or d.name,
            "link": d.link if links else "",
            "final": d.final,
        }
        for d in documents
    ]
    return out


# --- search -----------------------------------------------------------------------------------


def result_data(
    item: dict, run: Run | None, with_applications: bool, description: str = ""
) -> dict[str, Any]:
    """One row of ``search_detail()["results"]``; ``description``: the listing's full text."""
    hit_view = item["hit"]
    reasons = item["reasons"]
    hit = JobHit.model_validate({k: v for k, v in hit_view.items() if k in JobHit.model_fields})
    also = [SOURCES[k].label if k in SOURCES else k for k in hit.also_on]
    application = None
    if run is not None:
        match = (run.state or {}).get("match") or {}
        application = {
            "anchor": f"run-{run.id}" if with_applications else "",
            "status": STATUS_LABELS.get(str(run.status), str(run.status)),
            "tone": tone(str(run.status)),
            "verdict": VERDICTS.get(match.get("verdict", ""), ""),
            "verdict_key": match.get("verdict", ""),
            "score": match.get("score"),
        }
    return {
        "score": round(item["score"]),
        "title": hit.title,
        "url": hit.view_url or hit.url,
        "company": hit.company or "",
        "location": hit.location or "",
        "work": work_mode(hit.remote, hit.onsite_days_per_week),
        "salary": salary(hit.salary_min, hit.salary_max, hit.salary_currency, hit.salary_period),
        "posted": long_date(hit.posted_at) if hit.posted_at else "",
        "source": hit_view.get("source_label") or hit.source,
        "also_on": also,
        "new": bool(item.get("is_new")),
        "hidden": HIDDEN_LABELS.get(item["hidden"] or "", ""),
        "matched": reasons.get("matched_skills", []),
        "title_fit": percent(reasons.get("title_fit")),
        "meaning": percent(reasons.get("semantic_fit")),
        "basis": reasons.get("basis", "description"),
        "notes": reasons.get("notes", []),
        "excerpt": excerpt(description or hit_view.get("excerpt", "")),
        "application": application,
    }


def search_data(
    detail: dict,
    show: set[str],
    runs: dict[int, Run],
    ranking_text: str,
    with_applications: bool,
    descriptions: dict[int, str] | None = None,
) -> dict[str, Any]:
    """The search list: visible results, plus hidden ones whose reason is in ``show``.

    Listings with an application are always included in the full export.
    """
    results = []
    hidden_counts: dict[str, int] = {}
    for item in detail["results"]:
        run = runs.get(item["hit"].get("run_id") or -1)
        hidden = item["hidden"]
        keep = hidden is None or hidden in show or (with_applications and run is not None)
        if not keep:
            hidden_counts[hidden] = hidden_counts.get(hidden, 0) + 1
            continue
        text = (descriptions or {}).get(item["hit"]["id"], "")
        results.append(result_data(item, run, with_applications, text))
    sources = [
        {"label": s["label"], "count": s["count"], "error": s.get("error") or ""}
        for s in detail["sources"].values()
    ]
    return {
        "titles": detail["titles"],
        "places": detail["places"] or ["all of Germany"],
        "remote_only": detail["remote_only"],
        "created": long_date(detail["created_at"]),
        "requirements": [requirement_line(r) for r in detail["requirements"]],
        "sources": sources,
        "ranking": ranking_text,
        "total": detail["total"],
        "results": results,
        "not_included": ", ".join(
            f"{n} {HIDDEN_LABELS.get(k, k)}" for k, n in sorted(hidden_counts.items())
        ),
    }


def ranking_text(ranking: dict) -> str:
    """Same wording as the UI."""
    if ranking.get("semantic"):
        reused = f", {ranking['reused']} from earlier searches" if ranking.get("reused") else ""
        return (
            f"Ranked by meaning and keywords ({ranking.get('embedded') or 0} listings read"
            f"{reused})."
        )
    note = (ranking.get("note") or "").rstrip(".")
    return f"Ranked by keywords only: {note}." if note else "Ranked by keywords."


def export_data(
    *,
    kind: str,  # "search" | "full" | "application"
    title: str,
    candidate: ParsedCV | None,
    today: date,
    search: dict | None = None,
    applications: list[dict] | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "title": title,
        "generated": long_date(today),
        "candidate": {
            "name": candidate.contact.name if candidate else "",
            "headline": (candidate.headline or "") if candidate else "",
        },
        "search": search,
        "applications": applications or [],
    }
