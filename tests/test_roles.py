"""Alternative roles: Claude suggests them after confirmation, Python checks them."""

from datetime import date

from mappe.domain.extraction import to_parsed_cv
from mappe.domain.roles import RoleSuggestions, SuggestedRole
from mappe.search.models import JobHit
from mappe.search.queries import MAX_ROLES, filter_roles
from mappe.search.rank import rank
from tests.conftest import make_extracted
from tests.test_web import confirmed_cv, wait_for

CV = to_parsed_cv(make_extracted())


def role(title, ids=("pos1.resp1",), alt="", reason="Fits.") -> SuggestedRole:
    return SuggestedRole(title=title, title_alt=alt, reason=reason, fact_ids=list(ids))


def test_filter_keeps_roles_backed_by_cv_facts():
    kept = filter_roles(
        CV,
        [
            role("Platform Engineer (m/w/d)", ids=["cert1", "pos9.resp1"]),
            role("Astronaut", ids=["pos9.resp1"]),  # no real fact behind it
            role("Senior Backend Engineer"),  # the CV's own title already searched
            role("Python-Entwickler"),  # already a CV title variant
            role("platform engineer"),  # duplicate
            role("Tech Lead", alt="Backend Engineer"),  # alternative is already searched
            role("Data Engineer", alt="Dateningenieur"),
        ],
    )
    assert kept == [
        {"title": "Platform Engineer", "title_alt": "", "reason": "Fits.", "fact_ids": ["cert1"]},
        {"title": "Tech Lead", "title_alt": "", "reason": "Fits.", "fact_ids": ["pos1.resp1"]},
        {
            "title": "Data Engineer",
            "title_alt": "Dateningenieur",
            "reason": "Fits.",
            "fact_ids": ["pos1.resp1"],
        },
    ]


def test_filter_caps_the_number_of_roles():
    roles = [role(f"Role {i} Engineer") for i in range(MAX_ROLES + 3)]
    assert len(filter_roles(CV, roles)) == MAX_ROLES


def test_searched_titles_count_for_title_fit():
    hit = JobHit(
        source="arbeitnow",
        external_id="1",
        url="https://example.com/1",
        view_url="https://example.com/1",
        title="Platform Engineer (m/w/d)",
        description="Python, Kubernetes",
        posted_at=date(2026, 11, 1),
        language="en",
    )
    today = date(2026, 11, 4)
    without = rank([hit], CV, [], today=today)[0]
    chosen = rank([hit], CV, [], titles=["Platform Engineer"], today=today)[0]
    assert chosen.title_fit == 1.0 > without.title_fit
    assert chosen.score > without.score


def test_confirm_suggests_roles_and_search_offers_them(client, fake_llm):
    cv_id = confirmed_cv(client)
    cv = client.get(f"/api/cvs/{cv_id}").json()
    assert cv["roles_status"] == "done"
    assert [r["title"] for r in cv["roles"]] == [
        "Platform Engineer",
        "Data Engineer",
        "Tech Lead",
        "Site Reliability Engineer",
    ]
    call = next(c for c in fake_llm.calls if c["step"] == "suggest_roles")
    assert call["blocks"][0].text.startswith("<cv>\n") and "[pos1.resp1]" in call["context"]
    assert "- Backend Engineer" in call["task"]  # Claude is told what's already searched

    data = client.get(f"/api/search/suggestions?cv_id={cv_id}").json()
    assert "Platform Engineer" not in data["titles"]  # opt-in, not searched by default
    assert data["roles"][0] == {
        "title": "Platform Engineer",
        "title_alt": "",
        "reason": "You hold the CKA and run Python services in production.",
    }


def test_roles_can_be_suggested_again_and_reset_on_reparse(client, fake_llm):
    cv_id = confirmed_cv(client)
    fake_llm.results["suggest_roles"] = RoleSuggestions(roles=[role("Engineering Manager")])
    assert client.post(f"/api/cvs/{cv_id}/roles").status_code == 200
    cv = wait_for(client, f"/api/cvs/{cv_id}", lambda d: d["roles_status"] == "done")
    assert [r["title"] for r in cv["roles"]] == ["Engineering Manager"]

    client.put(f"/api/cvs/{cv_id}/markdown", json={"markdown": "# Jane Doe\n"})
    cv = wait_for(client, f"/api/cvs/{cv_id}", lambda d: d["status"] == "waiting_for_confirmation")
    assert cv["roles"] == [] and cv["roles_status"] is None
    assert client.post(f"/api/cvs/{cv_id}/roles").status_code == 409  # not confirmed


def test_failed_suggestion_is_shown_and_cv_stays_usable(client, fake_llm):
    fake_llm.results["suggest_roles"] = []  # popping from an empty list raises
    cv_id = confirmed_cv(client)
    cv = client.get(f"/api/cvs/{cv_id}").json()
    assert cv["status"] == "confirmed" and cv["roles_status"] == "failed" and cv["roles_error"]
    assert client.get(f"/api/search/suggestions?cv_id={cv_id}").json()["roles"] == []
