import { Button, GradientText } from "performative-ui";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api } from "../api";
import type { DocumentEdit } from "../api";
import { ErrorNote, Section, useAction } from "../components/ui";
import { useResource } from "../live";
import type { EditData } from "../types";

function initial(data: EditData): DocumentEdit {
  const { draft, cv } = data;
  const titles: Record<string, string> = {};
  draft.cv.titles.forEach((t) => (titles[t.id] = t.title));
  const bullets: Record<string, string[]> = {};
  cv.positions.forEach((p) => {
    bullets[p.id] = draft.cv.bullets.filter((b) => b.position_id === p.id).map((b) => b.text);
  });
  return {
    profile: draft.cv.profile,
    titles,
    bullets,
    skill_groups: [...draft.cv.skill_groups, { category: "", skills: [] }],
    letter: draft.letter
      ? { subject: draft.letter.subject, paragraphs: draft.letter.paragraphs.map((p) => p.text) }
      : null,
  };
}

export function EditPage() {
  const id = Number(useParams().id);
  const data = useResource(() => api.editData(id), [id]);
  const [edit, setEdit] = useState<DocumentEdit | null>(null);
  const action = useAction();
  const navigate = useNavigate();

  useEffect(() => {
    if (data.data) setEdit(initial(data.data));
  }, [data.data]);

  if (!data.data || !edit) return <div className="page"><ErrorNote error={data.error} /></div>;
  const { cv, draft, title } = data.data;
  const update = (patch: Partial<DocumentEdit>) => setEdit({ ...edit, ...patch });

  return (
    <div className="page">
      <div className="hero">
        <h1>
          <GradientText>Final review</GradientText>
        </h1>
        <p className="hero__sub">
          {title} · draft {draft.iteration}. Saving creates a new draft, renders it and runs the fact and ATS checks
          again (no AI calls). Problems are shown as warnings: you decide.
        </p>
      </div>

      <Section title="Profile">
        <textarea rows={4} value={edit.profile} onChange={(e) => update({ profile: e.target.value })} />
      </Section>

      {cv.positions.map((p) => (
        <Section key={p.id} className="edit-row" title={`${p.company}${p.client ? ` · ${p.client}` : ""}`}>
          <div className="edit-row__grid">
            <div className="stack">
              <label>
                Job title
                <input
                  value={edit.titles[p.id] ?? p.role}
                  onChange={(e) => update({ titles: { ...edit.titles, [p.id]: e.target.value } })}
                />
              </label>
              <label>
                Bullets (one per line, at most 5)
                <textarea
                  rows={Math.max(3, (edit.bullets[p.id]?.length ?? 0) + 1)}
                  value={(edit.bullets[p.id] ?? []).join("\n")}
                  onChange={(e) => update({ bullets: { ...edit.bullets, [p.id]: e.target.value.split("\n") } })}
                />
              </label>
            </div>
            <aside className="source">
              <h4>
                Your CV · {p.role}, {p.start}–{p.end ?? "present"}
              </h4>
              <ul>
                {[...p.responsibilities, ...p.achievements].map((f) => (
                  <li key={f.id}>{f.text}</li>
                ))}
              </ul>
              {p.technologies.length > 0 && <p className="muted">{p.technologies.join(", ")}</p>}
            </aside>
          </div>
        </Section>
      ))}

      <Section title="Skills" eyebrow="Only skills from your CV pass the fact check">
        <div className="stack">
          {edit.skill_groups.map((g, i) => (
            <div className="req-row req-row--wide" key={i}>
              <label>
                Category
                <input
                  value={g.category}
                  onChange={(e) => {
                    const groups = [...edit.skill_groups];
                    groups[i] = { ...g, category: e.target.value };
                    update({ skill_groups: groups });
                  }}
                />
              </label>
              <label>
                Skills (comma-separated)
                <input
                  value={g.skills.join(", ")}
                  onChange={(e) => {
                    const groups = [...edit.skill_groups];
                    groups[i] = { ...g, skills: e.target.value.split(",").map((s) => s.trimStart()) };
                    update({ skill_groups: groups });
                  }}
                />
              </label>
            </div>
          ))}
          <Button variant="ghost" size="sm" onClick={() => update({ skill_groups: [...edit.skill_groups, { category: "", skills: [] }] })}>
            Add group
          </Button>
        </div>
      </Section>

      {edit.letter && (
        <Section title="Cover letter" eyebrow="Salutation and closing are added automatically">
          <div className="stack">
            <label>
              Subject
              <input value={edit.letter.subject} onChange={(e) => update({ letter: { ...edit.letter!, subject: e.target.value } })} />
            </label>
            <label>
              Body (paragraphs separated by an empty line)
              <textarea
                rows={18}
                value={edit.letter.paragraphs.join("\n\n")}
                onChange={(e) => update({ letter: { ...edit.letter!, paragraphs: e.target.value.split(/\n\s*\n/) } })}
              />
            </label>
          </div>
        </Section>
      )}

      <Section className="sticky-actions">
        <ErrorNote error={action.error} />
        <div className="actions">
          <Button
            variant="glow"
            sparkle
            loading={action.busy}
            onClick={async () => {
              const saved = await action.run(() => api.saveDocuments(id, edit));
              if (saved) navigate(`/runs/${id}#documents`);
            }}
          >
            Save and check
          </Button>
          <Button as={Link} to={`/runs/${id}`} variant="ghost">
            Cancel
          </Button>
        </div>
      </Section>
    </div>
  );
}
