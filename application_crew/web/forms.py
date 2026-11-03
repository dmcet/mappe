"""Requirement form <-> Requirement models."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from application_crew.domain.models import Requirement

# Single-value structured requirements: form field -> requirement kind.
STRUCTURED = {
    "salary_min": "salary_min",
    "max_onsite_days": "max_onsite_days",
    "location": "location",
}


def requirements_from_form(form: Mapping[str, Any]) -> list[Requirement]:
    reqs: list[Requirement] = []
    for field, kind in STRUCTURED.items():
        value = str(form.get(field, "")).strip()
        if value:
            must = str(form.get(f"{field}_must", "")) in {"on", "1", "true"}
            reqs.append(Requirement(kind=kind, value=value, must_have=must))
    for field, must in (("must_other", True), ("nice_other", False)):
        for line in str(form.get(field, "")).splitlines():
            if line.strip():
                reqs.append(Requirement(kind="other", value=line.strip(), must_have=must))
    return reqs


def form_defaults(requirements: list[dict[str, Any]]) -> dict[str, Any]:
    """Pre-fill the form with the requirements of a previous run."""
    out: dict[str, Any] = {"must_other": [], "nice_other": []}
    for raw in requirements:
        req = Requirement.model_validate(raw)
        if req.kind in STRUCTURED.values():
            out[req.kind] = req.value
            out[f"{req.kind}_must"] = req.must_have
        else:
            out["must_other" if req.must_have else "nice_other"].append(req.value)
    out["must_other"] = "\n".join(out["must_other"])
    out["nice_other"] = "\n".join(out["nice_other"])
    return out
