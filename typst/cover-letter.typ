// Cover letter. Layout: letter-pro (MIT), DIN 5008 form B.
// All content comes from data.json and is inserted as plain text.
#import "vendor/letter-pro/src/lib.typ": letter-simple

#let d = json("data.json")
#let s = d.sender

#set text(lang: d.lang, size: 11pt, font: "New Computer Modern")
#set par(spacing: 1.4em)

#show: letter-simple.with(
  sender: (
    name: s.name,
    address: s.address,
    extra: [#s.contact.join(linebreak())],
  ),
  recipient: [#d.recipient.join(linebreak())],
  date: d.date,
  subject: d.subject,
)

#d.salutation

#for p in d.paragraphs [
  #p

]

#d.closing
#v(1cm)
#s.name
