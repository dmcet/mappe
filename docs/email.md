# Sending an application by email

When a finished application has a cover letter and the listing gives an email address,
the **Ready to send** panel offers to send it by email:

- **To:** the application address from the listing
- **Subject:** the cover letter's subject
- **Text:** the cover letter: greeting, paragraphs, closing and your name, phone and email
- **Attachment:** the final CV PDF

Mappe never sends email itself and stores no mail passwords. It hands the email to your mail
app, where you check it and press Send. It then goes out from your normal account and lands
in your "Sent" folder.

## Greeting

The greeting comes from the contact person in the listing:

| Listing says | German | English |
|---|---|---|
| "Frau Dr. Anna Schmidt" | Sehr geehrte Frau Dr. Schmidt, | Dear Dr. Schmidt, |
| "Herr Jan Weber" | Sehr geehrter Herr Weber, | Dear Mr Weber, |
| "Kim Weber" (no Frau/Herr) | Guten Tag Kim Weber, | Dear Kim Weber, |
| no name | Sehr geehrte Damen und Herren, | Dear Hiring Team, |

Frau/Herr is only used when the listing writes it. It is never guessed from the first name.
The PDF cover letter uses the same greeting and names the contact in the address block.

## Where the contact comes from

The listing parse (Haiku, the call that already runs) also reads the contact name and email
address. Python keeps them only if the listing text shows them: the name must appear in the
text, the address in the text or in the page's JSON-LD (`applicationContact`). Without an
address from Claude, a scan of the text picks one: one that matches the contact name or looks
like an application address (`bewerbung@`, `jobs@`, `karriere@`, ...), or the only one there.
Addresses like `noreply@` or `datenschutz@` are never used. Applications parsed before this
feature only get the text scan, and the neutral greeting.

The detected contact is shown on the application page under **Listing → Contact**.

## Mac: "Open in Apple Mail" (one-time shortcut setup)

The button runs an Apple Shortcut called **Mappe Mail**. The shortcut fetches the email from
Mappe, downloads the CV and opens a filled-in Apple Mail window with the CV attached. Build it
once in the **Shortcuts** app:

1. **File → New Shortcut**, name it exactly `Mappe Mail`.
2. Add **Get Contents of URL**. Set the URL to **Shortcut Input** (Mappe passes the address of
   the email data, e.g. `http://127.0.0.1:8000/api/runs/3/email`).
3. Add **Get Dictionary from Input** (input: *Contents of URL*).
4. Add **Get Dictionary Value**: key `cv_url`, from *Dictionary*. Then **Get Contents of URL**
   with that value as the URL. This downloads the CV PDF.
5. Add **Get Dictionary Value**: key `cv_name`, from *Dictionary*. Then **Set Name** of the
   downloaded *Contents of URL* to that value, so the attachment keeps its proper file name.
6. Add three more **Get Dictionary Value** actions for the keys `to`, `subject` and `body`.
   Tip: put a **Set Variable** after each one (`To`, `Subject`, `Body`) to keep them apart.
7. Add **Send Email**: Recipients `To`, Subject `Subject`, Message `Body` followed by the
   renamed file from step 5 (that makes it the attachment). Turn **Show Compose Sheet** on.

The first time, macOS asks whether the page may open Shortcuts and whether the shortcut may
connect to `127.0.0.1`. Allow both.

The shortcut has no fixed address in it. Mappe passes its own address, as you opened it in
the browser, so another port or host works without changes.

## Windows and Linux: "Download email (.eml)"

The `.eml` file is the complete email with the CV attached, marked as an unsent draft
(`X-Unsent: 1`).

- **Outlook** (Windows): opens it as a draft ready to send.
- **Thunderbird**: open it, then **Message → Edit as New Message**.
- **Apple Mail** opens it as a received message. Use **Message → Send Again** (⇧⌘D) to turn
  it into a draft. The shortcut above is the smoother way on a Mac.

## When there's no email button

The panel says why: the application isn't finished, there is no cover letter (the email text
is the cover letter), or the listing gives no email address.
