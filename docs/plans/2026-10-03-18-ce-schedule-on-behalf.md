# #18 — CE schedules a visit on behalf of a section's faculty / visitor

> Implemented inline (native execution). Written against `feat/issues-16-19` @ `4907d9b`.

**Goal:** CE staff can start scheduling a visit for any section from `/ce/class_visits/`.
The visitor list matches what faculty see (active `CourseAdministrator`s in
`CLASS_VISIT_ROLES`), and the visit records that CE scheduled it and who did.

**Architecture:** Reuse the existing CE form and view (`CEVisitScheduleForm`,
`views/ce.py::manage_visit`). Add a section picker that opens in the visits-page iframe
modal and links each row to `ce_manage_visit`. Visitor eligibility moves to
`services/scope.py::class_visit_administrators()`, which the faculty form already uses. The audit lives in
`VisitSchedule.meta`, so no migration is needed.

## Decisions

- **Roles**: `CLASS_VISIT_ROLES` = Faculty / Visitor / Dept. Chair / Dean (confirmed by the user).
- **Edit carve-out**: a visitor already on the visit stays selectable even if no longer
  eligible, labelled "— currently scheduled". The same rule already applies to sections (#12), so
  that saving the form never silently drops data.
- **Audit**: set on create only. `meta['scheduled_by_id']`, `meta['scheduled_by']` (name),
  `meta['scheduled_via']` (`'ce'` | `'faculty'`). The faculty form records `'faculty'` so the two
  can be told apart. Older visits have no keys and show nothing.
- **Notifications**: unchanged (CE form already offers email visitors / instructor). No new
  "notify faculty" email (YAGNI; the visitors *are* the faculty being scheduled for).

## Review Focus

1. A user with two active admin rows on the course (e.g. Faculty + Dept. Chair) → listed once.
2. An inactive admin, or one in a non-visit role (e.g. `Coordinator`) → not listed.
3. Editing a visit whose visitor has since gone inactive → still listed, still checked, kept on save.
4. Picker hides sections on the Not-Needed list and sections outside `section_status_filter`.
5. A CE-scheduled visit shows up in that visitor's faculty visits list.

## Tasks

### Task 1: visitor eligibility in `CEVisitScheduleForm`
**Files:** `forms/ce.py`; test `tests/test_ce_schedule_on_behalf.py`; adjust the mock in `tests/test_ce.py::CEVisitScheduleFormTest` if it patches `forms.ce.CourseAdministrator`.
- [ ] Failing tests for focus items 1–3.
- [ ] Implement: `class_visit_administrators([anchor.course_id])`, dedupe by user, then append existing visitors with the suffix.

### Task 2: on-behalf audit
**Files:** `forms/ce.py::save`, `forms/faculty.py::save`, `models.py` (`scheduled_by_display` property), `ce/_view_report_body.html`.
- [ ] Failing tests: CE save (with `request`) writes `scheduled_via='ce'` + `scheduled_by_id`; edit doesn't overwrite; faculty save writes `scheduled_via='faculty'`; CE view report shows "Scheduled By … (CE)".
- [ ] Implement.

### Task 3: "Schedule a Visit" entry point
**Files:** `views/ce.py::schedule_picker`, `urls/ce.py` (`ce_schedule_picker`), `templates/class_visit/ce/schedule_picker.html`, `ce/index.html` button.
- [ ] Failing tests: index shows the button; picker lists an eligible section with a link to `ce_manage_visit`; excludes not-needed and filtered-status sections; honours `term_id` / `course_id`; non-CE user refused (the `_ce` guard).
- [ ] Implement; confirm a CE-scheduled visit appears in the visitor's faculty API list (focus 5).
- [ ] Full suite, README/CLAUDE.md notes, commit.
