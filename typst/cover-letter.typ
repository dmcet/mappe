// Cover letter. All content comes from data.json and is inserted as plain text.
// layout "letter": letter-pro (MIT), DIN 5008 form B; only with a confirmed employer address.
// layout "plain": the same text without address blocks (no address known for the employer).
#import "vendor/letter-pro/src/lib.typ": letter-simple

#let d = json("data.json")
#let s = d.sender
#let font = "Inter"

#set text(lang: d.lang, size: 10.5pt, font: font, hyphenate: false)
#set par(spacing: 1.4em)

#let body = [
  #d.salutation

  #for p in d.paragraphs [
    #p

  ]

  #d.closing
  #v(1cm)
  #s.name
]

#if d.layout == "letter" {
  show: letter-simple.with(
    font: font,
    sender: (
      name: s.name,
      address: s.address,
      extra: [#s.contact.join(linebreak())],
    ),
    recipient: [#d.recipient.join(linebreak())],
    date: d.date,
    subject: d.subject,
  )
  body
} else {
  set page(paper: "a4", margin: (left: 25mm, right: 20mm, top: 25mm, bottom: 20mm))
  set par(justify: false)
  text(size: 15pt, weight: "semibold", s.name)
  linebreak()
  text(size: 9.5pt, fill: luma(80), s.contact.join("  ·  "))
  v(18mm)
  align(right, d.date)
  v(8mm)
  text(weight: "bold", d.subject)
  v(6mm)
  body
}
