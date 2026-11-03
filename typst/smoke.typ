// Smoke-test template: verifies the Typst toolchain and the data.json contract.
// Real CV / cover letter templates (RenderCV-based, DIN 5008) are added later.
#let data = json("data.json")
#set page(paper: "a4", margin: 2cm)
#set text(font: "Liberation Sans", size: 11pt, lang: data.at("lang", default: "en"))

= #data.title

#data.body
