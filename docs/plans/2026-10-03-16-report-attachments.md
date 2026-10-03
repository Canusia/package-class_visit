# #16 — Explore how visit reports handle file attachments

> Investigation issue. Implementation = the write-up in
> [`docs/report-attachments.md`](../report-attachments.md) plus the doc corrections below.
> Written against `v0.0.18` / `cd06752`.

**Goal:** Describe how report attachments work today, accurately enough for the
client_management workbook and settings export, and recommend a direction.

**Architecture:** No code change. Findings come from reading the model, views, templates,
PDF service and tests, and were confirmed by grep (no download route exists).

## Tasks

- [x] **1. Trace every code path that touches `VisitReportFile`.** Model (`models.py:471`),
  the single writer (`views/instructor.py::sign_report`), readers (`services/pdf.py::_signoff_context`,
  unused `VisitReport.visit_files_html`, unused `VisitReportFileSerializer`), and templates
  (`instructor/_report_detail_body.html` upload input, `letter_body.html` names list).
- [x] **2. Answer the five questions in the issue** → `docs/report-attachments.md`.
- [x] **3. Correct the package docs** that describe attachments:
  - `docs/class-visit-configuration-workbook.md` 4.3 asks clients a question the product
    cannot act on (visitors have no upload). Replace it with a statement of current behaviour.
  - `docs/class-visit-native-capabilities.md` "File Attachments" row: note the file is
    stored but not yet downloadable in the UI.
- [x] **4. Commit** (`docs: report attachments write-up (#16)`).

## Follow-ups recommended (not done here)

1. **Bug (from #14):** add the scoped attachment download view #14 specified
   (owner instructor / visitors / CE → 200, everyone else → 404) and list the files on
   the CE, faculty and instructor report pages. Until then, uploaded files can't be
   retrieved anywhere in the UI.
2. Add upload limits (size cap + extension allow-list) to the instructor upload.
3. Visitor attachments, if a client needs them, as a `report_fields_json` `file` field type.
