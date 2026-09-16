# #14 — Instructor sign-off: typed attestation, response and attachments

Supersedes **#7** (instructor acknowledgement/response) and absorbs **#9 part B**
(attachments advertised but unreachable). Close #7 as covered when this ships.

## Decisions taken

1. **Typed attestation, not a drawn pad.** The instructor types their name; we store it
   with a real timestamp. Reasons in "Why not the signature pad" below. Switching to a pad
   later is a field-type change, not a redesign.
2. **Login required**, instructor role, scoped to their own visits. No tokenized link.
3. **The control lives on the instructor report detail page**, not the row — you sign what
   you have read. The visits list shows a signed/unsigned indicator only.
4. **One sign-off per report, immutable once given**, and a faculty re-submission
   invalidates it (below).
5. **Response = textarea + optional file upload.**
6. **Real model fields**, not `meta` — "which reports are unsigned" must be queryable.
7. **The response appears in the instructor's own public-only PDF.**
8. **The visitor is emailed when an instructor responds**, behind a Yes/No setting.

Advisory throughout: nothing here gates report submission, status, notifications or any
existing flow. A report with no sign-off stays fully valid.

## Model changes (migration `0009`)

`VisitReport`:

| Field | Type | Notes |
|---|---|---|
| `instructor_signature` | `CharField(max_length=255, blank=True)` | typed name, or `'Marked as signed by {user}'` for a CE override — the platform sentinel (`cis/views/student.py:1440`), checked with `.startswith('Marked')` |
| `instructor_signed_on` | `DateTimeField(null=True, blank=True)` | a real DateTimeField. mou stores an `m/d/Y H:M` **string** in JSON and pays to re-parse it (`mou/settings/helpers.py:135`); `cis` uses `DateField` and silently drops the time (`cis/models/student.py:2510`). Repeat neither. |
| `instructor_response` | `TextField(blank=True)` | the written response |
| `instructor_responded_on` | `DateTimeField(null=True, blank=True)` | separate from signing: a response can arrive without a signature |

`VisitReportFile` (currently `id`, `visit_report`, `uploaded_at`, `file`):

| Field | Type | Notes |
|---|---|---|
| `uploaded_by` | `FK('cis.CustomUser', null=True, on_delete=SET_NULL)` | who attached it; null keeps historic rows loadable |
| `kind` | `CharField(choices=[('faculty_attachment',…), ('instructor_response',…)], default='faculty_attachment')` | the model cannot currently tell a visitor's evidence from an instructor's rebuttal |

Migration dependencies must be `('class_visit', '0008_…')` and `('cis', '__first__')` —
never a tenant-specific cis migration number (`0008_add_class_visit_menu_items.py:112-115`
is the pattern). The `submod-migration-deps` skill applies.

## Setting

One `YES_NO` ChoiceField, `instructor_signature`, default **No**, so no existing tenant
changes behaviour on upgrade. `payment_tracking` (`settings/class_visit.py:198`) is the
precedent: a toggle whose only job is deciding whether one role's affordance appears.

Three keys for the new notification (#5's shape): `notify_visitor_on_response` (YES_NO,
default No), `visitor_response_subject`, `visitor_response_message`, with shortcodes
`{{visitor_first_name}}`, `{{teacher_first_name}}`, `{{teacher_last_name}}`,
`{{visit_date}}`, `{{class_sections}}`, `{{report_url}}` (from #4).

All four go into `install()`'s defaults — **land #10 first**, or adding keys is exactly
what triggers the config wipe it describes.

## UI and flow

- **Instructor report detail** (`views/instructor.py:97`, template
  `instructor/_report_detail_body.html`): when the setting is Yes and the report is
  `Submitted`, render a sign-off panel — a typed-name `CharField` ("Please type your
  name"), a response `Textarea`, and a file input. Needs `enctype="multipart/form-data"`,
  whose absence is half of why attachments were unreachable.
- **POST route** `instructor_class_visit:sign_report`, `report/<uuid:visit_id>/sign/`,
  `@login_required` + `@require_POST`, scoped with `_get_teacher_or_none(request)` and
  `VisitSchedule.objects.filter(class_sections__teacher=teacher)` — the same guard the
  existing instructor views use (`views/instructor.py:167-170`). Refuse when the report is
  not `Submitted`, and refuse a second signature.
- **Once signed**, the panel renders read-only: the typed name, the timestamp, the
  response and any files. Signature and response are never editable in place.
- **Faculty re-submission invalidates the signature**: when a report goes Draft →
  Submitted again, clear `instructor_signature` and `instructor_signed_on` so the
  attestation never refers to a document that has since changed. **Keep** the response
  text and files — those are the instructor's own words, not an attestation about a
  specific version — and note in the UI that the report has been revised since. The clear
  belongs in `VisitReportDynamicForm.save()` where the status flips
  (`forms/faculty.py:308-315`).
- **Attachments** are downloadable by the report's faculty visitor(s), the instructor who
  owns the visit, and CE. `VisitReportFile.file` uses `PrivateMediaStorage`, so serve
  through a scoped view, never a raw storage URL.

## Letter / PDF

`templates/class_visit/letter_body.html` currently ends on the dynamic-rows table with no
signature block at all. Add a block after it:

- Instructor: typed name (or "Marked as signed by …"), signed date, or
  "Not yet signed" when blank — mirroring `MOUSignature.signature_asHTML`
  (`mou/models.py:581-592`).
- The response text, and attachment filenames (names only; the PDF cannot embed them).
- Include all of it in the instructor's `public_only=True` PDF (decision 7) and in the CE
  and faculty PDFs.

## Notification

`notify_visitor_response(visit_report)` in `services/emails.py`, gated on
`notify_visitor_on_response == 'Yes'`, recipients = the visit's visitors, stamping
`instructor_response_email_sent_on`. Follow the guard-then-send shape of
`notify_visitor_payment_processed` (`services/emails.py:225-251`) rather than
`notify_notification_target`, which is the ungated one #5 fixes.

## Tests

`class_visit/tests/test_instructor_signoff.py` (new):

1. Setting `No` → no panel rendered, and a direct POST to the sign route is refused.
2. Setting `Yes`, report `Submitted` → panel renders; POST stores the typed name,
   a non-null `instructor_signed_on`, and the response.
3. Draft report → no panel, POST refused.
4. Another instructor's visit → 404, nothing written (mirrors
   `tests/test_instructor_report_details.py:174-185`).
5. Second signature attempt → refused; the first values are unchanged.
6. Faculty re-submit clears signature and `signed_on`, keeps `instructor_response` and
   files.
7. Response with a file → one `VisitReportFile` with `kind='instructor_response'` and
   `uploaded_by` set; a faculty-side attachment keeps `kind='faculty_attachment'`.
8. Attachment download: owner instructor 200, visitor 200, CE 200, unrelated instructor
   404, unrelated faculty 404.
9. Letter HTML/PDF shows the typed name and response, and shows "Not yet signed" when
   absent; `public_only=True` still includes the response.
10. Email fires only when the setting is Yes, to the visitors, with a non-empty
    `{{report_url}}`; nothing fires on signature-without-response.
11. Nothing here changes report `status`, and submission still works with the setting on
    and no signature — the advisory guarantee.

## Why not the signature pad

`FFields.SignatureField` / `SignatureWidget` (`/repos/form_fields/form_fields/fields/signature.py`)
is what mou, parent consent and drop_wd use, and it was the obvious "follow mou" answer.
Three properties ruled it out here:

1. **It would post an empty signature on this page.** The widget writes the data URL only
   on click of `document.querySelector("input.submit")`. The report UI submits via
   `<button type="button">` + `fetch()` (`faculty/edit_visit_report.html:28-40`), so
   nothing triggers serialization. Every existing consumer carries a defensive `clean()`
   for exactly this (`mou/forms.py:775`, `cis/forms/student.py:1065`,
   `drop_wd/forms.py:294`).
2. **CSP.** The pad loads `signature_pad@2.3.2` from jsdelivr, and the platform's
   `Content-Security-Policy` allows `script-src 'self' https://js.stripe.com`
   (`cis/middleware.py:11-13`). It is Report-Only today, so nothing breaks yet; enforcing
   it later would break every pad in the platform. Don't add a fourth dependant.
3. The widget's Clear button is broken (stray `#` inside the `id`), and `drop_wd` writes
   PNG data URLs into `CharField(max_length=50)` — a live truncation bug. The widget is
   not well-tended.

The typed attestation matches what your own student-facing flows already do — FERPA
(`myce_tenant_configs/services/ferpa_form.py:52-60`) and the student agreement
(`cis/forms/student.py:879-885`) both type a name — with no CDN and no submit coupling.
