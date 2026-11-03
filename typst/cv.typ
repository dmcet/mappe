// Tailored CV. Layout: basic-resume (Unlicense), single column, ATS-friendly.
// All content comes from data.json (prepared by application_crew/render/documents.py)
// and is inserted as plain text, never evaluated as markup.
#import "vendor/basic-resume/src/lib.typ": resume, work, edu, certificates

#let d = json("data.json")
#let c = d.contact

#show: resume.with(
  author: d.name,
  location: c.location,
  email: c.email,
  github: c.github,
  linkedin: c.linkedin,
  phone: c.phone,
  personal-site: c.site,
  accent-color: "#1f3a68",
  paper: "a4",
  font-size: 10pt,
  lang: d.lang,
)

// ATS: no hyphenation (it splits keywords across lines) and no justification.
#set text(hyphenate: false)
#set par(justify: false)

#if d.headline != "" [
  #v(-0.4em)
  #text(size: 11pt)[#d.headline]
]

#if d.profile != "" [
  == #d.labels.profile
  #d.profile
]

== #d.labels.experience
#for p in d.positions {
  block(width: 100%, breakable: true, {
    work(title: p.title, company: p.company, location: p.location, dates: p.dates)
    if p.bullets.len() > 0 { list(..p.bullets) }
  })
}

#if d.skills.len() > 0 [
  == #d.labels.skills
  #for g in d.skills {
    block(width: 100%, [*#g.category:* #g.items])
  }
]

#if d.education.len() > 0 [
  == #d.labels.education
  #for e in d.education {
    block(width: 100%, edu(institution: e.institution, degree: e.degree, location: e.location, dates: e.dates, consistent: true))
  }
]

#if d.certifications.len() > 0 [
  == #d.labels.certifications
  #for x in d.certifications {
    block(width: 100%, certificates(name: x.name, issuer: x.issuer, date: x.date))
  }
]

#if d.extra.len() > 0 [
  == #d.labels.extra
  #list(..d.extra)
]

#if d.languages != "" [
  == #d.labels.languages
  #d.languages
]
