# #5 — Office "report submitted" email reuses the instructor's copy and cannot be disabled

## Problem (verified)

`notify_notification_target` (`services/emails.py:145-193`) sends the institution's
"report submitted" notification using the **instructor's** settings verbatim
(`:186-187`):

```python
subject = cfg.get('teacher_submit_subject', 'Visit Report Submitted')
message = render_template(cfg.get('teacher_submit_message', ''), ctx)
```

It is called on submit from `forms/faculty.py` with **no Yes/No guard**, unlike
`notify_teacher_on_schedule` and `notify_teacher_on_submit`, which each check a setting
first. Recipients are the active `administrator` CourseAdministrators for the visit's
courses, or `generic_email`, per `notify_target` (`:157, 170-182`).

Consequences:

- Instructor copy is addressed to the person who was observed. EWU's approved text opens
  "Thank you for participating in your EWU in the High School faculty site visit… your
  faculty mentor has completed the site visit evaluation form." Course administrators
  receive that, addressed as though they were the high-school teacher.
- It cannot be turned off at all.
- The two sends build **different contexts**, so one body cannot serve both well even if
  the tone were fixed: the office context has `class_sections` (`:162-167`) and the
  instructor context has `public_report_url` (`:132-137`) — neither has the other's key.

## Fix

Three new settings keys on `settings/class_visit.py`, following the existing shapes
(`notify_teacher_on_submit` at `:150` is the Yes/No precedent, `teacher_submit_*` the
subject/body precedent):

| Key | Type | Purpose |
|---|---|---|
| `notify_office_on_submit` | `YES_NO` ChoiceField | gate the send |
| `office_submit_subject` | CharField | its own subject |
| `office_submit_message` | CharField/Textarea | its own body |

Then:

1. Add all three to the `install()` defaults dict (`:375-393`) — and land #10 first, or
   adding keys is what triggers the wipe it describes.
2. `notify_notification_target` gates on `notify_office_on_submit == 'Yes'` and reads its
   own subject/body, falling back to the `teacher_submit_*` values when the new body is
   blank. The fallback is what keeps existing tenants sending the same email they send
   today; without it, upgrading silently stops a notification an office relies on.
3. Give the office context both keys — add `public_report_url` (#4) alongside
   `class_sections`, and document the full shortcode list for the new body:
   `{{teacher_first_name}}`, `{{teacher_last_name}}`, `{{visit_date}}`,
   `{{class_sections}}`, `{{public_report_url}}`.
4. Update `README.md` and `docs/class-visit-configuration-workbook.md` (§ on
   notifications) with the new keys.

## Decisions (defaults chosen, change if you disagree)

- **Default for `notify_office_on_submit`: `Yes`.** Today the send is unconditional, so
  defaulting to `No` would silence an existing notification on upgrade. New tenants get it
  on, matching current behaviour; a tenant that does not want it now has a switch.
- **Default body: empty, with the `teacher_submit_*` fallback.** An empty default plus
  fallback reproduces today's emails exactly until an admin writes office copy. The
  alternative — shipping generic office wording as the default — changes what every
  tenant sends the moment they upgrade.
- If you would rather ship suggested office wording, it belongs in the workbook as copy to
  paste, not in `install()`.
- **Recipients stay as they are.** The target keeps being active `CourseAdministrator`
  rows with role exactly `Administrator` (or `generic_email`). Note the deliberate tension
  with #8: `Administrator` plays no part in class-visit *access*, so these recipients
  cannot open the visit the email refers to. That is intended — this is a heads-up to a
  records inbox, not a call to action. Do not "fix" it by widening the role list, and do
  not add a report link expecting them to click it.

## Tests (`class_visit/tests/test_office_submit_email.py`, new)

1. `notify_office_on_submit='No'` → nothing sent, and `meta['course_admin_email_sent_on']`
   is not stamped.
2. `='Yes'` with office subject/body set → those are used, not the instructor's.
3. `='Yes'` with office body blank → falls back to `teacher_submit_message` (the
   upgrade-compatibility guarantee).
4. The office body renders `{{class_sections}}` **and** `{{public_report_url}}`
   non-empty (ties to #4).
5. Both `notify_target` modes still resolve recipients as before
   (`course_administrator` → active administrators; `generic_email` → the configured
   address; blank → no send).
6. The instructor send is unaffected by all of the above (no cross-wiring).
7. `meta['course_admin_email_sent_on']` is still stamped on a successful send, and the
   existing `VisitReport.objects.filter(...).update(meta={...})` write (`:189-192`) does
   not clobber other meta keys written by the same submit.

## Notes

- Point 7 is worth a hard look while in here: that `update()` rewrites the whole `meta`
  dict from an instance read before the send. If anything else wrote meta in between, it
  is lost. Out of scope to redesign, in scope to not make worse.
