# Visitor file uploads on the visit report (+ instructor access)

> Follows #16 (`docs/report-attachments.md`). Implemented inline (native execution).
> Written against `feat/issues-16-19` @ `33e7cda`.

**Goal:** When the tenant turns it on, visitors can attach files to a visit report. A second
setting decides whether the instructor can see and download them. CE and the visit's
visitors can always download a report's attachments.

**Architecture:** Reuse the existing `VisitReportFile` model. Its `kind` field already marks who
uploaded the file: `faculty_attachment` (label "Visitor attachment") or `instructor_response`
(label "Instructor response"). `uploaded_by` and `uploaded_at` also already exist. A second
type field would duplicate `kind`, so there is **no new model and no migration**. Files stay
in `PrivateMediaStorage` and are only reachable through scoped download views (#16 found none existed).

## Decisions

| Topic | Decision |
|---|---|
| Settings | `visitor_file_upload` (Yes/No, default No) — "Visitors Can Attach Files to the Report". `instructor_view_visitor_files` (Yes/No, default No) — "Instructor Can Download Visitor Files"; shown only when uploads are Yes (toggle JS, like payment). |
| Upload | Multiple files per save, optional. Max 10 MB each; extensions pdf, doc(x), xls(x), ppt(x), txt, csv, jpg/jpeg, png, gif, heic. Field name `cv_visitor_files`, which a report-field `name` is unlikely to collide with. |
| Removing | A visitor (or CE) can remove a *visitor* attachment while the report is still a Draft. After submission the attachments are fixed. |
| Download — CE | Any attachment on any report. |
| Download — visitors | Any attachment on their visit's report (visitor files and the instructor's response files, as #14 intended). |
| Download — instructor | Their own `instructor_response` files always. Visitor files only when `instructor_view_visitor_files = Yes`, and only for a **Submitted** report on their own visit. Everything else is 404. |
| Turning uploads off later | Existing files stay visible and downloadable; only *new* uploads stop. |
| Letter PDF | Unchanged (still lists instructor-response names only). |

## Review Focus

1. Oversized file or disallowed extension → the form error is returned as JSON, and no report or file is saved.
2. Instructor guesses another visit's file id, or a file id from a different visit in the URL → 404.
3. Instructor with the setting off → no list on the page, and the direct URL returns 404 for visitor files.
4. Draft report saved with files and no other changes → files are stored (draft save must not drop them).
5. Remove on a Submitted report, or of an instructor-response file, by a visitor → refused.

## Tasks

### Task 1: settings
**Files:** `settings/class_visit.py` (fields, install defaults, toggle JS), `tests/test_settings_class_visit.py`.
- [ ] Failing tests: both fields exist; install seeds both as `No`.
- [ ] Implement; extend the toggle script to hide `instructor_view_visitor_files` unless uploads = Yes.

### Task 2: upload on the report form
**Files:** create `services/uploads.py` (limits, `MultipleFileField`, `uploads_enabled()`,
`instructor_sees_visitor_files()`, `save_visitor_files()`, `attachment_rows()`, `file_response()`);
`forms/faculty.py::VisitReportDynamicForm`; `views/faculty.py::edit_visit_report`;
`faculty/edit_visit_report.html`.
- [ ] Failing tests: setting off → no `cv_visitor_files` field; on → a draft POST with 2 files stores
  2 `VisitReportFile(kind='faculty_attachment', uploaded_by=visitor)`; an 11 MB file or `.exe` → 400 with
  the error and nothing stored.
- [ ] Implement.

### Task 3: download / remove views + listings
**Files:** `views/{faculty,ce,instructor}.py`, `urls/{faculty,ce,instructor}.py`, templates
`class_visit/_attachments.html` (shared list), `faculty/edit_visit_report.html`,
`ce/_view_report_body.html`, `instructor/_report_detail_body.html`.
- [ ] Failing tests: the access matrix above (CE 200; visitor 200; unrelated faculty 404; instructor 404 when off,
  200 when on and submitted, 404 when draft; file from another visit 404); remove rules (focus 5);
  instructor page lists visitor files only when on.
- [ ] Implement.

### Task 4: docs + commit
- [ ] Workbook 4.3 back as a real two-part question; capabilities row; `docs/report-attachments.md`
  current state; README settings list; CLAUDE.md.
- [ ] Full suite, commit.
