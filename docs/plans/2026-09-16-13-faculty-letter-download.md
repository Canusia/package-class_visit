# #13 — Faculty cannot download visit letters

## Problem (verified)

Two gaps combine into "no working download for faculty".

**1. Bulk export filters the wrong table.** The DataTable checkbox carries a
**VisitSchedule** id (`templates/class_visit/faculty/visits.html:202`, rows served by
`FacultyVisitScheduleSerializer`, `serializers/faculty.py:82`). The view filters
**VisitReport** primary keys with those ids (`views/faculty.py:259-262`):

```python
VisitReport.objects.filter(
    id__in=raw_ids,
    visit_schedule__class_sections__course__id__in=course_ids).distinct()
```

Disjoint UUID sets, so the queryset is always empty and the view returns
`{'success': False, 'message': 'No reports found.'}` with 404 (`:264`). The view's own
docstring (`:247`) says it expects report ids, so the wire format and the view disagree.

Both dropdown options fail identically: the JS rewrites `action` to `export_pdf` for both
and only varies `public_only` (`visits.html:276-296`).

**CE does the same POST correctly** (`views/ce.py:389-394`): it takes schedule ids and maps
each to `visit.report`, skipping missing ones.

**2. No per-row download.** The faculty actions column renders Edit Report / Edit Visit /
Delete only (`visits.html:234-251`). CE and instructor both have a single-letter route
(`class_visit:ce_report_pdf` → `views/ce.py:273`; `instructor_class_visit:report_pdf` →
`views/instructor.py:156`). Faculty has none, so there is no fallback.

## Fix

**Part 1 — bulk.** Resolve schedule ids to reports, keeping the existing authorization
scope (`CourseAdministrator`-active courses, `views/faculty.py:256-262`):

```python
visits = VisitSchedule.objects.filter(
    pk__in=raw_ids,
    class_sections__course__id__in=course_ids,
).distinct()
reports = [v.report for v in visits if v.has_report()]
```

`visit_schedule` is a `OneToOneField` (`models.py:327-330`), so a schedule maps to zero or
one report; skip the empty ones rather than 404ing the whole batch. Keep the 404 +
"No reports found." only when nothing resolves. Fix the docstring to say schedule ids.

**Part 2 — per-row.** Add `faculty_class_visit:report_pdf` at
`visits/<uuid:visit_id>/pdf/`, modelled on `views/ce.py:273` but scoped like the faculty
bulk path, calling `visit_letter_pdf(report, public_only=False)` (`services/pdf.py:45`).
Render the button in the actions column only when the row has a report — the serializer
already exposes enough to decide, or add a `has_report` field to it.

Keep `public_only=False` for faculty: they are the authors, and the bulk "All Fields"
option already gives them everything.

## Tests

`class_visit/tests/test_faculty_letter_download.py` (new), with **real rows** — no ORM
mocks (see README):

1. Two visits with reports, one in the faculty user's `CourseAdministrator` scope and one
   outside; bulk POST of both schedule ids → PDF returned, and
   `visit_letters_pdf` called with only the in-scope report.
2. Bulk POST of a schedule with **no** report → 404 "No reports found.", and the PDF
   service is not called.
3. Mixed batch (one with report, one without) → 200, only the existing report exported.
4. `public_only=1` reaches the service as `public_only=True`.
5. Per-row: in-scope visit with report → 200 `application/pdf`; out-of-scope → 404 and
   `visit_letter_pdf` not called; in-scope with no report → 404.
6. The actions column renders the download button only for rows with a report.

Also fix `tests/test_views_faculty.py:175-250`: it patches `VisitReport` and stubs
`objects.filter().distinct()`, which is why this shipped. Rewrite it against real rows in
the same change, or delete it in favour of the new file.

## Notes

- CE's bulk path has **no object-level scoping at all** (`views/ce.py:372-402`, only the
  `user_has_cis_role` URL guard). That is consistent with CE seeing everything, so it is
  not part of this fix — but it means CE is not a reference for authorization, only for id
  mapping.
- Faculty JS does a native form POST while CE uses an AJAX blob download
  (`staticfiles/class_visit/js/ce_visits.js:212-260`). Native POST is fine for a file
  response; leave it rather than widening the change.
