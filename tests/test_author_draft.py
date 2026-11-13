"""CV reworks: Claude returns only the changes, Python merges them into the previous draft."""

from mappe.domain.author import (
    AuthorBullet,
    AuthorCV,
    BulletChange,
    SkillGroup,
    Title,
    apply_draft,
    full_draft,
    render_for_rework,
)
from mappe.llm.demo import demo_author_cv


def b(pid, text, ids=None):
    return AuthorBullet(position_id=pid, text=text, fact_ids=ids or [f"{pid}.resp1"])


def change(action, item="", after="", pid="", text="", ids=None):
    return BulletChange(
        action=action, item=item, after=after, position_id=pid, text=text, fact_ids=ids or []
    )


def previous() -> AuthorCV:
    return AuthorCV(
        profile="Old profile.",
        profile_fact_ids=["pos1"],
        titles=[Title(id="pos1", title="Engineer"), Title(id="pos2", title="Developer")],
        bullets=[b("pos1", "A"), b("pos1", "B"), b("pos2", "C")],
        skill_groups=[SkillGroup(category="Languages", skills=["Python"])],
        extra=[b("proj1", "Side project", ["proj1"])],
    )


def no_changes():
    return full_draft(previous()).model_copy(
        update={
            "profile": "",
            "profile_fact_ids": [],
            "titles": [],
            "bullets": [],
            "skill_groups": [],
            "extra": [],
        }
    )


def texts(doc):
    return [x.text for x in doc.bullets]


def test_first_draft_is_taken_as_is():
    doc = demo_author_cv()
    assert apply_draft(None, full_draft(doc)) == doc


def test_an_empty_rework_keeps_everything():
    assert apply_draft(previous(), no_changes()) == previous()


def test_replace_delete_and_add_by_label():
    draft = no_changes()
    draft.bullets = [
        change("replace", item="B2", pid="pos1", text="B2 new", ids=["pos1.resp2"]),
        change("delete", item="B1"),
        change("add", after="B3", pid="pos2", text="D"),
        change("add", pid="pos2", text="first of pos2"),  # no 'after': first in its position
        change("add", pid="pos9", text="new position"),  # unknown position: at the end
    ]
    doc = apply_draft(previous(), draft)
    assert texts(doc) == ["B2 new", "first of pos2", "C", "D", "new position"]
    assert doc.bullets[0].fact_ids == ["pos1.resp2"]


def test_moving_a_bullet_to_the_top():
    draft = no_changes()
    draft.bullets = [change("delete", item="B2"), change("add", pid="pos1", text="B")]
    assert texts(apply_draft(previous(), draft)) == ["B", "A", "C"]


def test_unknown_labels_and_repeated_bullets_are_tolerated():
    draft = no_changes()
    draft.bullets = [
        change("delete", item="B7"),  # ignored
        change("replace", item="B9", pid="pos1", text="E"),  # becomes an add
        change("add", after="B1", pid="pos1", text="A", ids=["pos1.resp1"]),  # already there
    ]
    assert texts(apply_draft(previous(), draft)) == ["E", "A", "B", "C"]


def test_profile_titles_skills_and_extra():
    draft = no_changes()
    draft.profile, draft.profile_fact_ids = "New profile.", ["pos2"]
    draft.titles = [Title(id="pos2", title="Senior Developer"), Title(id="edu1", title="M.Sc.")]
    draft.skill_groups = [SkillGroup(category="Tools", skills=["Git"])]
    draft.extra = [change("delete", item="E1")]
    doc = apply_draft(previous(), draft)
    assert (doc.profile, doc.profile_fact_ids) == ("New profile.", ["pos2"])
    assert [t.title for t in doc.titles] == ["Engineer", "Senior Developer", "M.Sc."]
    assert doc.skill_groups == draft.skill_groups and doc.extra == []


def test_the_rework_view_labels_every_item():
    text = render_for_rework(previous())
    assert "Profile [pos1]: Old profile." in text
    assert "B3 (pos2) [pos2.resp1]: C" in text and "E1 (proj1) [proj1]: Side project" in text
    assert "Titles: pos1: Engineer; pos2: Developer" in text
    empty = previous().model_copy(update={"extra": []})
    assert render_for_rework(empty).endswith("Additional experience:\n(none)")
