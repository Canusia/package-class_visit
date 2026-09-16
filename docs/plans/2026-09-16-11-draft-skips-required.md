# #11 — "Save as Draft" must skip required-field validation

## Problem (verified)

`views/faculty.py:196-221` validates before it knows the intent:

```python
form = VisitReportDynamicForm(visit=visit, initial_meta=initial_meta, data=request.POST)
if form.is_valid():
    report = form.save(created_by_user=request.user)
```

The action is only read inside `save()` (`forms/faculty.py:308-309`:
`submit_action = data.get('submit_action', 'draft').lower()`), and
`services/report_fields.py:110` applies each definition's `required` flag
unconditionally. The template posts the intent in a hidden field, set by
`submitReport('draft'|'submit')` (`templates/class_visit/faculty/edit_visit_report.html:28-40`).

So with any required field configured, "Save as Draft" returns 400 with field errors and
saves nothing. A tenant with 11 required fields cannot save a draft at all.

## Fix

Relax requirements when the intent is a draft, at the place that builds the fields.

1. `build_report_form_fields(..., enforce_required: bool = True)`
   (`services/report_fields.py:93`): when `enforce_required` is False, build every field
   with `required=False`.
   **Watch the select branch** (`:128-136`): the blank `('', '---')` choice is only added
   for non-required fields, so relaxing must also add it, or a blank dropdown fails
   validation with "not a valid choice" — the same bug wearing a different hat.
2. `VisitReportDynamicForm.__init__` reads the intent from its own bound data
   (`data.get('submit_action')`), defaulting to `'draft'`, and passes
   `enforce_required=(intent == 'submit')`. Keep the default: an unbound form (GET) renders
   with the real required markers so the user sees which fields Submit will demand.
3. `save()` keeps deciding the status from `submit_action` — unchanged.

No view change is needed, which keeps the fix in one place for the CE side too if a CE
report form is added later.

## Tests (`class_visit/tests/test_report_draft_validation.py`, new)

With a settings fixture whose `report_fields_json` has one required `text`, one required
`select` and one optional field:

1. Draft with everything blank → `is_valid()` is True; report saved with `status='Draft'`;
   view returns 200 and `{'status': 'draft'}`.
2. Draft with a blank required **select** → valid (the regression the blank choice hides).
3. Submit with blanks → invalid; errors name every required field; nothing saved.
4. Submit complete → `status='Submitted'`.
5. Draft then submit: the draft's values survive as `initial` and the submit succeeds.
6. GET renders required fields as required (so the form still communicates intent).
7. A `date` field left blank on draft does not break `save()`'s meta coercion
   (`coerce_meta_value`, `forms/faculty.py:317-322`).

## Notes

- A draft stores `''` for skipped fields. That is what the pre-existing code does for
  optional blanks, so no migration or cleanup is needed.
- Submitting still goes through the full `required` set, so the guarantee tenants care
  about ("a submitted report is complete") is unchanged.
