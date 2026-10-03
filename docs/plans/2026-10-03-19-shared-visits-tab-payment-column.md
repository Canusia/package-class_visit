# #19 — Hide Payment Status in the shared visits tab when payment tracking is off

> Implemented inline (native execution). Written against `feat/issues-16-19` @ `a140e02`.

**Goal:** `templates/schedule/class_visits.html` (the Visit(s) tab on seven CE detail pages)
shows the Payment Status column only when `payment_tracking = Yes`, like the CE index.

**Architecture:** The includers live in `cis` and pass no flag, so the partial works it out
itself through a new template tag,
`{% class_visit_payment_tracking as payment_tracking_enabled %}` (in
`class_visit/templatetags/class_visit_tags.py`). The tag returns the context's
`payment_tracking_enabled` when a caller set one, and otherwise calls
`services/payment.py::payment_tracking_enabled()` (added in #17). `cis` needs no change.

## Global Constraints

- `templatetags/` is a Python package, so `packages = find:` ships it (needs `__init__.py`);
  no MANIFEST change.
- The library name `class_visit_tags` must not collide with any other installed app (checked: none).

## Review Focus

1. Tracking off → no `<th>` **and** no JS column; a mismatch makes DataTables warn.
2. Tracking on → unchanged from today (`data: 'payment_status'`).
3. A caller-supplied `payment_tracking_enabled` wins over the DB (lets `SimpleTestCase`
   renders stay DB-free).

## Tasks

### Task 1: tag + partial
**Files:** create `class_visit/templatetags/__init__.py`, `class_visit/templatetags/class_visit_tags.py`;
modify `templates/schedule/class_visits.html`; tests `tests/test_embedded_visits_tab.py`,
`tests/test_ce.py::SharedVisitsTablePaymentColumnTest`.
- [ ] Failing tests: with the setting No (DB, `TestCase`) → no `Payment Status` header and no
  `payment_status` column; Yes → both present; context override wins.
  `SimpleTestCase` renders pass `payment_tracking_enabled` explicitly.
- [ ] Implement the tag; wrap the `<th>` and the JS column object in `{% if payment_tracking_enabled %}`.
- [ ] Full suite; CLAUDE.md note; commit.
