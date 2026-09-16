# #4 — {{public_report_url}} and {{report_url}} render empty

## Decision taken

**Both links require login.** No tokenized public report view, no new
unauthenticated surface. The links point at the existing per-portal pages; a recipient
who is not signed in lands on the login page and arrives after signing in.

That leaves the confirmation-token flow (`services/confirmation.py`) as the only
login-free route in the package, unchanged by this plan.

## Problem (verified)

Three sends pass the shortcode in as a literal empty string, with TODO comments
confirming it was left unfinished (`services/emails.py`):

| Function | Line | Shortcode | Setting body | Recipient |
|---|---|---|---|---|
| `notify_teacher_report_submitted` | `:136` | `{{public_report_url}}` | `teacher_submit_message` | instructor(s) of the visited sections |
| `remind_visitor_report_pending` | `:212` | `{{report_url}}` | `visitor_reminder_message` | each visitor (faculty) |
| `notify_visitor_payment_processed` | `:248` | `{{report_url}}` | `visitor_paid_message` | each visitor (faculty) |

`render_template` (`:23-28`) is plain Django `Template`/`Context`, so an empty or missing
key renders as nothing at all — no error, no literal `{{...}}`, no log line. The
shortcodes are advertised in `settings/class_visit.py:165-169, 183-186, 222-225`, in
`README.md:146` and in `docs/class-visit-configuration-workbook.md:206, 246, 273`, so
implementers write copy around links that never appear.

A fourth case, same root: `notify_notification_target` (`:145-193`) renders
`teacher_submit_message` with a context that has no `public_report_url` key at all
(`:162-167`), so the office copy of that body drops the link too.

## Fix

**1. One URL helper** in `services/emails.py` (or a small `services/urls.py`), following
the established absolute-URL pattern — `Site.objects.get_current()` + `reverse`, as
`services/confirmation.py:22-24` does. Emails have no request, so `Site` (or
`cis.utils.getDomain()`, `cis/utils.py:818-829`) is the only option. Do not hardcode a
scheme separately from the existing helper; reuse whichever one the package already
trusts and note the choice in the docstring.

**2. `{{public_report_url}}`** → `instructor_class_visit:report_detail`
(`urls/instructor.py:33-37`, route `report/<uuid:visit_id>/`). It takes the **schedule**
id, not the report id, and already forces public-only fields
(`views/instructor.py:97-115`) with teacher scoping — which is exactly what an instructor
should see of their own visit. Populate it in `notify_teacher_report_submitted` and
**also** in `notify_notification_target`'s context, so the shared body stops rendering a
blank link for the office copy. (Whether the office should have its own wording is #5.)

**3. `{{report_url}}`** → `faculty_class_visit:edit_visit_report`
(`urls/faculty.py:45-49`). For the overdue reminder this is the right target: the action
being nagged about *is* writing the report. Reuse it for the payment-processed email so
one shortcode has one meaning.

Two caveats to handle rather than ignore:
- That page is built for an iframe modal (`@xframe_options_exempt`, template has its own
  `<body>`). Verify it renders standalone; if it looks wrong outside the modal, add a thin
  read-only faculty report page and point the shortcode there instead. Decide by looking,
  not by assuming.
- It currently has **no ownership check** (`views/faculty.py:190`) — see the README's
  unfiled finding. Emailing the URL to visitors does not create the hole, but it does put
  it in writing to users; fix that separately and ideally first.

**4. Naming.** `{{public_report_url}}` now unambiguously means "the instructor's
public-fields view, login required". Keep the shortcode name for tenant compatibility and
update the three help_texts, `README.md` and the workbook to say the links require
sign-in.

## Tests (`class_visit/tests/test_report_url_shortcodes.py`, new)

1. Each of the three bodies configured as `'Link: {{report_url}}'` /
   `'{{public_report_url}}'` renders an absolute `https://<site domain>/...` URL
   containing the schedule UUID — mock `Site` the way
   `tests/__init__.py:369-380` does for `confirmation_url`.
2. The instructor URL resolves to `instructor_class_visit:report_detail` and the faculty
   URL to `faculty_class_visit:edit_visit_report` (assert via `reverse`, not a string).
3. `notify_notification_target` renders a non-empty link for the same body.
4. No body renders an empty string where a shortcode was used — the regression guard:
   assert the rendered output does not contain `'Link: \n'` / an empty anchor.
5. Existing gating still holds: each send stays behind its Yes/No setting and recipient
   rules (`tests/test_notify_visitor_paid.py`, `tests/test_send_visit_report_reminders.py`
   already cover this — extend, don't duplicate).

## Notes

- `tests/test_email_html_rendering.py` asserts markup survives into the HTML body and is
  stripped for text/plain. A URL is plain text, so no HTML-escaping question arises — but
  add the link to that test's body fixture so both parts are exercised.
- Docs to update in the same commit: `settings/class_visit.py` help_texts (3),
  `README.md:146`, `docs/class-visit-configuration-workbook.md:206, 246, 273`.
