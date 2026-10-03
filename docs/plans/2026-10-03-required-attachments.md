# Required attachments: visitor report and instructor sign-off

> Follows `2026-10-03-visitor-report-uploads.md`. Implemented inline.
> Written against `feat/issues-16-19` @ `a44fa30`.

**Goal:** A tenant can require a file (a) on every **submitted** visit report and (b) on every
instructor sign-off / response.

**Architecture:** Two Yes/No settings, both default No and both shown only when their parent
feature is on. Visitor enforcement lives in `VisitReportDynamicForm.clean()`. Instructor
enforcement lives in `views/instructor.py::sign_report`, which redirects back with
`?signoff_error=file_required`. The panel shows that inline, so it works in both the full page
and the ajax modal. The rule in both cases is "at least one file of your own kind": either one
already on the report or one in this request.

## Decisions

| Topic | Decision |
|---|---|
| Visitor setting | `visitor_file_required` — "Require a File to Submit the Report". Shown when `visitor_file_upload = Yes`; ignored otherwise. |
| When enforced | On **Submit** only. Save as Draft never requires it (same rule as required report fields, #11). |
| Satisfied by | One `faculty_attachment` already on the report, or one uploaded in the same POST. Removing the last file from a draft means Submit fails until a file is added. |
| Instructor setting | `instructor_file_required` — "Require a File with the Instructor Sign-Off". Shown when `instructor_signature = Yes`; ignored otherwise. |
| Instructor enforced | Any sign-off POST (signature and/or response) is refused with nothing written, unless the instructor already has an `instructor_response` file on the report or uploads one now. The panel shows "(required)", and the input gets `required` when no file exists yet. |
| Existing reports | Not retroactively invalid. The rule applies on the next submit / sign-off. |

## Review Focus

1. Draft save with the visitor requirement on and no files → saved (200), not rejected.
2. Submit with an existing visitor file and no new upload → accepted.
3. Requirement on but uploads off → ignored (no field to satisfy it).
4. Instructor POST without a file when required → no signature, response or file stored; the error shows.
5. Instructor with an earlier response file → can sign without uploading again.

## Tasks

### Task 1: settings
`settings/class_visit.py` fields, install defaults, toggle JS. Test data dicts in `tests/__init__.py` and
`tests/test_settings_class_visit.py` gain the keys.

### Task 2: visitor enforcement
`forms/faculty.py::VisitReportDynamicForm.clean`, `services/uploads.py`
(`visitor_file_required()`, label). Tests in `tests/test_required_attachments.py`.

### Task 3: instructor enforcement
`views/instructor.py::sign_report` + `report_detail` context, `instructor/_report_detail_body.html`.
Tests in the same file.

### Task 4: docs, full suite, commit
Workbook (4.3b and the sign-off section), README, CLAUDE.md, `docs/report-attachments.md`.
