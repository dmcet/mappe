// Export report in the look of the Mappe UI (dark theme, performative-ui tokens).
// All content comes from data.json (prepared by mappe/export/data.py) and is inserted as
// plain text, never evaluated as markup. Fonts: typst/fonts (Inter, Instrument Serif,
// JetBrains Mono; OFL).

#let d = json("data.json")

// ---------- tokens (as in frontend/src/app.css: neutral grays, navy accent) ----------
#let bg = rgb("#0a0a0b")
#let panel-fill = rgb("#111113")
#let elev = rgb("#18181b")
#let border = rgb("#232326")
#let border-bright = rgb("#303035")
#let fg = rgb("#f2f2f3")
#let dim = rgb("#a8a8ae")
#let mute = rgb("#86868d")
// navy accent (the CV's #1f3a68 and light tints of it)
#let navy = rgb("#1f3a68")
#let accent = rgb("#4f72a8")
#let accent-mid = rgb("#7f9dc8")
#let accent-to = rgb("#a9bfdd")
#let link-color = rgb("#8fa9d1")
#let good = rgb("#22c55e")
#let you = rgb("#fbbf24")
#let bad = rgb("#f87171")
#let busy = rgb("#8fa9d1")
#let grad = gradient.linear(accent, accent-mid, accent-to, angle: 15deg)
#let tones = (good: good, bad: bad, you: you, busy: busy, muted: mute, neutral: dim)
#let verdict-colors = (apply: good, consider: you, dont_apply: bad)
#let sans = "Inter"
#let serif = "Instrument Serif"
#let mono = "JetBrains Mono"

// ---------- page ----------
#let glow = {
  place(rect(width: 100%, height: 100%, fill: gradient.radial(
    (navy.transparentize(55%), 0%), (navy.transparentize(100%), 100%),
    center: (0%, 0%), radius: 75%,
  )))
  place(rect(width: 100%, height: 100%, fill: gradient.radial(
    (accent.transparentize(88%), 0%), (accent.transparentize(100%), 100%),
    center: (100%, 100%), radius: 60%,
  )))
}

#let star(size: 10pt) = {
  let s = size / 32
  box(baseline: 12%, polygon(
    fill: grad,
    (16 * s, 2 * s), (19.2 * s, 11.6 * s), (29 * s, 14.8 * s), (19.2 * s, 18 * s),
    (16 * s, 30 * s), (12.8 * s, 18 * s), (3 * s, 14.8 * s), (12.8 * s, 11.6 * s),
  ))
}

// Gradient text, as GradientText in the UI. Boxed when it fits on one line, so the
// gradient spans the text rather than the page width.
#let gradtext(body) = layout(size => {
  let w = measure(body).width
  if w <= size.width { box(text(fill: grad, body)) } else { block(text(fill: grad, body)) }
})

#set document(title: d.title, author: "Mappe")
#set page(
  paper: "a4",
  fill: bg,
  background: glow,
  margin: (x: 16mm, top: 21mm, bottom: 19mm),
  header: context {
    if here().page() > 1 {
      set text(size: 8pt, fill: mute)
      grid(
        columns: (auto, 1fr),
        align: (left + horizon, right + horizon),
        [#star(size: 9pt) #h(2pt) #text(weight: "bold", fill: fg)[Mappe]],
        d.title,
      )
    }
  },
  footer: context {
    set text(size: 7.5pt, fill: mute)
    grid(
      columns: (1fr, auto),
      [Generated with Mappe · #d.generated],
      text(font: mono)[#here().page() / #counter(page).final().first()],
    )
  },
)
#set text(font: sans, size: 9.5pt, fill: fg, lang: "en", hyphenate: false)
#set par(leading: 0.62em, justify: false, spacing: 0.9em)
#set list(marker: text(fill: accent-mid, size: 8pt, baseline: -0.5pt)[●], indent: 2pt, body-indent: 6pt, spacing: 0.55em)
#set enum(indent: 2pt, body-indent: 6pt, spacing: 0.55em, numbering: n => text(font: mono, fill: link-color, size: 8pt)[#n])
#show link: set text(fill: link-color)
#show heading: set text(font: serif, weight: "regular")
#show heading.where(level: 1): it => block(above: 0pt, below: 9pt, gradtext(text(size: 26pt, it.body)))

// ---------- components ----------
#let eyebrow(body, color: mute) = text(size: 7pt, weight: "semibold", tracking: 0.1em, fill: color, upper(body))

#let panel(body, eyebrow: none, title: none, accent: none, breakable: true, aside: none) = block(
  width: 100%,
  breakable: breakable,
  fill: panel-fill,
  stroke: 0.6pt + if accent == none { border } else { accent.transparentize(45%) },
  radius: 12pt,
  inset: (x: 14pt, y: 12pt),
  above: 0pt,
  below: 10pt,
  {
    if eyebrow != none or title != none or aside != none {
      grid(
        columns: (1fr, auto),
        align: (left + bottom, right + bottom),
        {
          if eyebrow != none { block(below: 3pt, text(size: 7pt, weight: "semibold", tracking: 0.1em, fill: if accent == none { mute } else { accent }, upper(eyebrow))) }
          if title != none { block(below: 0pt, text(size: 11.5pt, weight: "semibold", title)) }
        },
        if aside != none { aside },
      )
      v(6pt)
    }
    body
  },
)

#let badge(body, color: dim) = box(
  inset: (x: 6pt, y: 2.5pt),
  radius: 99pt,
  fill: elev,
  stroke: 0.6pt + color.transparentize(55%),
  text(size: 7.5pt, weight: "semibold", fill: color, body),
)

#let chip(body, color) = box(
  inset: (x: 5pt, y: 2pt),
  radius: 4pt,
  fill: color.transparentize(86%),
  text(size: 7.5pt, weight: "semibold", fill: color, body),
)

#let tag(body) = box(
  inset: (x: 6pt, y: 2pt),
  radius: 99pt,
  fill: elev,
  stroke: 0.5pt + border-bright,
  text(size: 7.5pt, fill: fg, body),
)
#let tags(items) = if items.len() > 0 { block(above: 4pt, below: 6pt, items.map(tag).join(h(4pt))) }

#let outcome(body, tone) = text(font: mono, size: 8pt, fill: tones.at(tone, default: dim), body)
#let small-head(body) = block(sticky: true, above: 10pt, below: 5pt, text(size: 7pt, weight: "semibold", tracking: 0.08em, fill: mute, upper(body)))
#let muted(body) = text(fill: dim, body)
#let source(body) = if body != "" { text(size: 7.5pt, fill: mute)[ — #body] }

#let kv(pairs) = grid(
  columns: (auto, 1fr),
  column-gutter: 14pt,
  row-gutter: 6pt,
  ..pairs.map(((k, v)) => (text(fill: mute, k), v)).flatten(),
)

#let rows-table(columns, header, rows) = table(
  columns: columns,
  stroke: (x, y) => (bottom: 0.5pt + border),
  inset: (x: 5pt, y: 5pt),
  align: left + top,
  table.header(..header.map(h => text(size: 6.8pt, weight: "semibold", tracking: 0.06em, fill: mute, upper(h)))),
  ..rows.flatten(),
)

#let button(body, dest) = {
  let pill = box(
    inset: (x: 10pt, y: 5pt),
    radius: 99pt,
    fill: grad,
    text(size: 8.5pt, weight: "semibold", fill: white, body),
  )
  if dest != "" { link(dest, pill) } else { pill }
}

#let score-box(score) = box(
  width: 30pt,
  height: 30pt,
  radius: 8pt,
  fill: elev,
  stroke: 0.6pt + if score >= 70 { accent.transparentize(20%) } else { border-bright },
  align(center + horizon, text(font: mono, size: 11pt, weight: "bold", fill: fg, str(score))),
)

// ---------- hero ----------
#let kind-label = (search: "Job search", full: "Job search and applications", application: "Application").at(d.kind)

#block(below: 14pt, {
  block(below: 10pt, [#star(size: 13pt) #h(3pt) #text(size: 11pt, weight: "bold")[Mappe]])
  // A single application has its own title below; a search gets the big one.
  if d.search != none {
    eyebrow(kind-label)
    v(2pt)
    gradtext(text(font: serif, size: 34pt, d.search.titles.slice(0, calc.min(2, d.search.titles.len())).join(", ")))
    v(4pt)
  }
  set text(fill: dim)
  if d.candidate.name != "" [
    Candidate: #text(fill: fg, weight: "semibold", d.candidate.name)#if d.candidate.headline != "" [ · #d.candidate.headline]
    #linebreak()
  ]
  [Prepared on #d.generated. Links open the listings; ]
  if d.applications.len() > 0 [the tailored CVs and cover letters are separate files next to this report.] else [scores rank the listings against the candidate's CV.]
})

// ---------- search ----------
#let search-panel(s) = panel(eyebrow: "Search", title: [#s.results.len() listings · searched on #s.created], {
  let reqs = if s.requirements.len() == 0 { muted[none] } else {
    s.requirements.map(r => [#r.label: #r.value#if r.must [ #chip("must-have", you)]]).join(linebreak())
  }
  let sources = s.sources.map(x => if x.error != "" [#x.label #text(fill: bad)[#x.error]] else [#x.label #text(font: mono, weight: "bold")[#x.count]]).join(h(10pt))
  kv((
    ("Job titles", s.titles.join(", ")),
    ("Area", s.places.join(", ") + if s.remote_only { " · remote only" } else { "" }),
    ("Requirements", reqs),
    ("Sources", sources),
    ("Ranking", s.ranking + " Score 0–100 from the CV's skills found in the listing, title fit, meaning and freshness."),
    ..if s.not_included != "" { (("Not included", s.not_included),) } else { () },
  ))
})

#let glance(apps) = panel(eyebrow: "Applications", title: [At a glance], {
  rows-table(
    (auto, 1fr, auto, auto),
    ("Verdict", "Listing", "Status", "Page"),
    apps.map(a => (
      if a.verdict != none { chip(a.verdict.label + " · " + str(a.verdict.score), verdict-colors.at(a.verdict.key, default: dim)) } else { text(fill: mute)[—] },
      [#link(label(a.anchor), text(fill: fg, weight: "semibold", a.title))#if a.company != "" [ #muted[· #a.company]]],
      text(fill: tones.at(a.tone, default: dim), size: 8.5pt, a.status),
      context link(label(a.anchor), text(font: mono, size: 8.5pt)[p. #locate(label(a.anchor)).page()]),
    )),
  )
})

#let hit-card(r) = block(
  width: 100%,
  breakable: false,
  fill: panel-fill,
  stroke: 0.6pt + if r.application != none { accent.transparentize(40%) } else { border },
  radius: 12pt,
  inset: (x: 12pt, y: 10pt),
  above: 0pt,
  below: 7pt,
  grid(
    columns: (30pt, 1fr),
    column-gutter: 11pt,
    score-box(r.score),
    {
      block(below: 3pt, {
        link(r.url, text(fill: fg, weight: "semibold", size: 10pt, r.title))
        if r.new { h(6pt); text(size: 6.5pt, weight: "bold", tracking: 0.08em, fill: good)[NEW] }
        if r.hidden != "" { h(6pt); badge(r.hidden, color: mute) }
      })
      let meta = (r.company, r.location, r.work, r.salary).filter(x => x != "")
      if meta.len() > 0 { block(below: 2pt, text(size: 8.5pt, fill: dim, meta.join(" · "))) }
      let src = (r.source,) + if r.also_on.len() > 0 { ("also on " + r.also_on.join(", "),) } else { () } + if r.posted != "" { ("posted " + r.posted,) } else { () }
      block(below: 3pt, text(size: 7.5pt, fill: mute, src.join(" · ")))
      tags(r.matched)
      let fit = ()
      if r.title_fit != "" { fit.push("title fit " + r.title_fit) }
      if r.meaning != "" { fit.push("meaning " + r.meaning) }
      if r.basis != "description" { fit.push(r.basis) }
      if fit.len() > 0 { block(below: 3pt, text(font: mono, size: 7pt, fill: mute, fit.join("  ·  "))) }
      for n in r.notes { block(below: 2pt, text(size: 8pt, fill: you, n)) }
      if r.excerpt != "" { block(above: 4pt, below: 0pt, text(size: 8pt, fill: dim, r.excerpt)) }
      let a = r.application
      if a != none {
        block(above: 7pt, below: 0pt, {
          if a.verdict != "" { chip(a.verdict + if a.score != none { " · " + str(a.score) } else { "" }, verdict-colors.at(a.verdict_key, default: dim)); h(6pt) }
          badge(a.status, color: tones.at(a.tone, default: dim))
          if a.anchor != "" {
            h(8pt)
            context link(label(a.anchor), text(size: 8pt)[Assessment → p. #locate(label(a.anchor)).page()])
          }
        })
      }
    },
  ),
)

// ---------- application ----------
#let evidence-list(items) = list(..items.map(x => [#x.text#source(x.from)]))

#let application(a, new-page: true) = {
  if new-page { pagebreak(weak: true) }
  block(below: 12pt, {
    grid(
      columns: (1fr, auto),
      align: (left + bottom, right + bottom),
      eyebrow("Application" + if a.company != "" { " · " + a.company } else { "" }),
      badge(a.status, color: tones.at(a.tone, default: dim)),
    )
    v(3pt)
    [#heading(level: 1, a.title) #label(a.anchor)]
    set text(fill: dim, size: 9pt)
    if a.url != "" { link(a.url)[#a.host ↗] } else { a.host }
    if a.decision != "" [ · #a.decision]
  })

  let v = a.verdict
  if v != none {
    let color = verdict-colors.at(v.key, default: dim)
    panel(eyebrow: "Assessment", accent: color, breakable: false, {
      block(below: 8pt, {
        text(font: serif, size: 24pt, fill: color, v.label)
        h(10pt)
        text(font: mono, size: 15pt, fill: dim)[#v.score#text(size: 8pt)[/100]]
      })
      text(size: 10.5pt, v.rationale)
    })
  }

  if a.documents.len() > 0 {
    panel(eyebrow: "Documents", title: if a.documents.all(x => x.final) [Ready to send] else [Draft in final review, not yet approved], breakable: false, {
      block(below: 8pt, text(size: 8.5pt, fill: dim)[Separate files in the same archive as this report.])
      a.documents.map(doc => block(below: 6pt, {
        button([Open #doc.label ↗], doc.link)
        h(8pt)
        text(font: mono, size: 7.5pt, fill: mute, doc.file)
      })).join()
    })
  }

  if v != none {
    block(below: 10pt, grid(
      columns: (1fr, 1fr),
      column-gutter: 10pt,
      panel(title: "Strengths", {
        evidence-list(v.strengths)
        if v.transferable.len() > 0 {
          small-head("Transferable")
          list(..v.transferable.map(t => [*#t.missing*: #t.text#source(t.from)]))
        }
      }),
      panel(title: "Gaps", {
        if v.gaps.len() > 0 { list(..v.gaps) } else { muted[None found.] }
        if v.highlights.len() > 0 {
          small-head("Focus for the CV")
          enum(..v.highlights.map(h => [#h.text#source(h.from)]))
        }
      }),
    ))
  }

  if a.requirements.len() > 0 {
    panel(title: "Requirements", {
      rows-table(
        (auto, auto, 1fr),
        ("Requirement", "Outcome", "Why"),
        a.requirements.map(r => (
          [#r.label: #r.value#if r.must [ #chip("must", you)]],
          outcome(r.outcome, r.tone),
          [#r.note#if r.evidence != "" { block(above: 4pt, inset: (left: 7pt), stroke: (left: 1.5pt + border-bright), text(fill: dim, size: 8.5pt)["#r.evidence"]) }],
        )),
      )
    })
  }

  let rv = a.review
  if rv != none {
    let sub = [#rv.drafts draft(s) · final draft #rv.final#if rv.edited [ (edited by hand)]#if rv.stop_reason != "" [ · review stopped: #rv.stop_reason]]
    panel(eyebrow: "Review loop", title: "Checks of the final draft", aside: text(size: 8pt, fill: mute, sub), {
      rows-table(
        (auto, auto, 1fr),
        ("Check", "Result", "Details"),
        rv.checks.map(c => (text(weight: "semibold", c.name), outcome(c.outcome, c.tone), text(size: 8.5pt, c.detail))),
      )
      let rec = rv.recruiter
      if rec != none {
        small-head("Recruiter review")
        block(below: 6pt, {
          text(font: mono, size: 13pt, weight: "bold")[#rec.average#text(size: 8pt, fill: mute)[/5]]
          h(8pt)
          if rec.invite { chip("would invite", good) } else { chip("would not invite yet", you) }
          h(10pt)
          text(size: 8pt, fill: mute, rec.scores.map(s => [#s.name #text(fill: fg, weight: "bold", str(s.value))]).join(h(9pt)))
        })
        text(rec.summary)
        if rec.feedback.len() > 0 {
          block(above: 6pt, text(size: 8.5pt, fill: dim, list(..rec.feedback)))
        }
      }
    })
  }

  let cov = a.coverage
  if cov != none {
    panel(eyebrow: cov.summary, title: "Skill coverage", {
      block(below: 6pt, text(size: 8.5pt, fill: dim)[Computed from the CV: #cov.years.])
      rows-table(
        (1fr, auto, 1fr, auto),
        ("Skill", "Coverage", "From the CV", "Years"),
        cov.rows.map(c => (
          [#c.skill#if not c.required { muted[ (nice)] }],
          outcome(c.coverage, c.tone),
          text(size: 8.5pt, c.cv_skill),
          text(font: mono, size: 8pt, c.years),
        )),
      )
    })
  }

  let l = a.listing
  if l != none {
    panel(eyebrow: if a.company != "" { a.company } else { none }, title: "The listing", aside: if a.url != "" { link(a.url, text(size: 8.5pt)[Open listing ↗]) }, {
      kv((
        ("Location", l.location),
        ("Work mode", l.work),
        ("Salary", l.salary),
        ("Language", l.language),
      ))
      grid(
        columns: (1fr, 1fr),
        column-gutter: 14pt,
        {
          if l.required.len() > 0 { small-head("Required skills"); tags(l.required) }
          if l.nice.len() > 0 { small-head("Nice to have"); tags(l.nice) }
          if l.benefits.len() > 0 { small-head("Benefits"); list(..l.benefits) }
        },
        {
          if l.responsibilities.len() > 0 { small-head("Responsibilities"); list(..l.responsibilities) }
        },
      )
    })
  }
}

// ---------- document ----------
#if d.search != none {
  search-panel(d.search)
  if d.applications.len() > 0 { glance(d.applications) }
  block(above: 16pt, below: 8pt, [#heading(level: 1, outlined: true, text(size: 18pt)[Listings]) #label("listings")])
  if d.search.results.len() == 0 { muted[No listings to show.] }
  for r in d.search.results { hit-card(r) }
}
#for a in d.applications { application(a, new-page: d.search != none) }
