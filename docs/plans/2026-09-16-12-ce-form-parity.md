# #12 — CE scheduling form ignores section_status_filter and "visit not needed"

## Problem (verified)

`CEVisitScheduleForm.__init__` (`forms/ce.py:94-100`) builds section choices from the
anchor section only:

```python
sections = ClassSection.objects.filter(
    teacher=anchor.teacher, term=anchor.term, course=anchor.course)
```

No status filter, no exemption filter. The faculty form does both
(`forms/faculty.py:90-92` via `_status_filter_to_db`, then excludes ids present in
`NotNeededVisit`). So:

- `section_status_filter` ("active sections only") silently does not apply to CE staff.
- A section a CE user explicitly flagged "visit not needed" is still fully schedulable
  from the CE side — the exemption list appears to do nothing.

`NotNeededVisit.class_section` is a `OneToOneField` (`models.py:539-545`), so the exclusion
is a simple id set.

## Fix

In `forms/ce.py`, apply the same two rules the faculty form applies:

1. Move `_status_filter_to_db` into a shared place both forms import — `services/` or a
   small `forms/_shared.py`. Do not copy it; two copies of a settings-to-DB-code mapping
   is how they drift.
2. Filter the anchor query by `status__in=allowed_status_codes`.
3. Exclude sections present in `NotNeededVisit`.

**The edit carve-out (decision below).** When editing an existing visit
(`forms/ce.py:127-140` prepopulates from `visit_id`), a section already on that visit may
now be inactive or flagged not-needed. If the choices exclude it, the form silently drops
it and saving rewrites the visit without that section — turning a display filter into data
loss. The plan is: **always union in the sections already attached to the visit being
edited**, so filtering governs what you can *add*, never what you silently lose. Mark
those entries in the label (e.g. "— currently scheduled") so the CE user sees why an
otherwise-filtered section is listed.

## Tests (`class_visit/tests/test_forms_ce_parity.py`, new)

With settings `section_status_filter='active'`:

1. An inactive (`status='C'`) sibling section is absent from `class_sections` choices.
2. With `section_status_filter='all'`, it is present.
3. A section with a `NotNeededVisit` row is absent.
4. Anchor section itself remains present and pre-selected (`forms/ce.py:111`).
5. **Edit case:** a visit already attached to an inactive section keeps that section in
   the choices and in `initial`, and saving the unchanged form preserves it.
6. Parity: given identical settings and data, CE and faculty forms offer the same section
   id set (guards future drift).

## Notes

- Visitor choices (`forms/ce.py:114-123`) are `CourseAdministrator`-based on both sides
  already; no change.
- `type_of_visit` is `required=True` in both forms — that is issue #9's "Optional" workbook
  question, not this one. Leave it.
