# #17 — Payment tracking: complete the staff and visitor experience

> Implemented inline (native execution). Written against `v0.0.18` / `cd06752`.

**Goal:** With `payment_tracking = Yes`, CE can mark and un-mark submitted reports as paid in
bulk with a who/when audit trail. Payment status, date and who marked it appear in the
CE lists, the CE report page, the Visit Reports export, and the faculty/visitor list and
report page. All of it is hidden when tracking is off.

**Architecture:** The audit lives on `VisitReport` (`payment_processed` flag + `meta`). The new
helper `services/payment.py::payment_tracking_enabled()` replaces four copies of the
`ClassVisitSettings.from_db().get('payment_tracking', 'No') == 'Yes'` check. No migration:
the audit lives in `meta`.

## What already works (confirmed)

| Requirement | Status in v0.0.18 |
|---|---|
| CE Payment Status column, hidden when off | ✅ `ce/index.html` + `ce_visits.js` |
| Bulk mark paid, one email per newly-paid report | ✅ `views/ce.py::do_bulk_action` `mark_as_paid` (already-paid rows skipped, so no repeat email) |
| Only submitted reports | ✅ `VisitReport.can_payment_be_processed` |
| Faculty/visitor list column | ✅ `faculty/visits.html` |
| Paid **date** | ✅ `meta['payment_processed']` (`m/d/Y`) |

## Gaps closed here

1. **Who marked it**: not recorded. Add `meta['payment_processed_by']` (display name) and
   `meta['payment_history']` (append-only list of `{action, on, by_id, by}`).
2. **Un-mark**: there is no way to correct a mistake. Add `VisitReport.unmark_payment_processed(user)`,
   bulk action `mark_as_unpaid`, and a "Mark Selected as Unpaid" button. No email on un-mark.
3. **Status text**: `payment_status_sexy` → `Processed on 10/03/2026 by Jane Doe` (the
   " by …" part only when it was recorded).
4. **Export**: `reports/visit_reports.py` gains `Payment Status`, `Paid On`, `Paid By` columns
   when tracking is on.
5. **Report pages**: CE `_view_report_body.html` and faculty `edit_visit_report.html` show a
   Payment line for a submitted report when tracking is on.

## Global Constraints

- `payment_processed` values: `'1'` = paid; un-mark writes `'2'` (the `No` choice of
  `YES_NO_SELECT_OPTIONS`); legacy `''`/`'0'`/`'No'` stay "Pending".
- Keep the key `meta['payment_processed']` (the date string): emails and existing data read it.
- Never hardcode the `class_visit.` import prefix; relative imports only.

## Review Focus

1. Un-marking a report that is not paid → no-op, not counted, no history entry.
2. Re-marking after un-mark → paid again, emails again (it's a new payout event), history has 3 entries.
3. Legacy paid rows with no `payment_processed_by` → status reads `Processed on <date>` with no dangling " by".
4. Tracking off → `mark_as_unpaid` refused with 403, same as `mark_as_paid`.
5. Export with tracking off → header/row lengths unchanged from today.

## Tasks

### Task 1: model audit + helper
**Files:** `class_visit/models.py`, create `class_visit/services/payment.py`, test `class_visit/tests/test_payment_tracking.py`
- [ ] Failing tests: mark records `payment_processed_by` + one history entry; status text has " by <name>"; legacy row without `by` has no " by"; unmark resets to `'2'`, drops date/by, appends history; unmark on unpaid is a no-op returning False; `payment_tracking_enabled()` reads the setting.
- [ ] Implement `mark_as_payment_processed(user=None)` / `unmark_payment_processed(user=None) -> bool`, `payment_processed_by` property, `payment_tracking_enabled()`.
- [ ] Run tests → pass.

### Task 2: CE bulk un-mark + button
**Files:** `views/ce.py`, `templates/class_visit/ce/index.html`, `staticfiles/class_visit/js/ce_visits.js`, test in `test_payment_tracking.py`
- [ ] Failing tests: `mark_as_unpaid` 403 when off; un-marks paid report, count message `Unmarked 1 of 1`; sends no email; mark passes `request.user` (history `by_id` set); the index shows "Mark Selected as Unpaid" only when on.
- [ ] Implement: shared gate, the `mark_as_unpaid` branch, the button, a generic JS handler for both buttons.

### Task 3: export columns
**Files:** `reports/visit_reports.py`, test in `test_payment_tracking.py`
- [ ] Failing tests: tracking on → headers end the static block with `Payment Status, Paid On, Paid By` and row values match; off → no payment headers.
- [ ] Implement.

### Task 4: report pages
**Files:** `views/ce.py::view_report`, `views/faculty.py::edit_visit_report`, `ce/_view_report_body.html`, `faculty/edit_visit_report.html`
- [ ] Failing tests: CE view_report and faculty edit page show `Payment` + status text when on and the report is submitted; absent when off.
- [ ] Implement; swap the inline setting checks in `views/ce.py` / `views/faculty.py` for the helper.
- [ ] Full `class_visit` suite; update README/CLAUDE.md payment notes; commit.
