# Issue plans

One plan per issue in `Canusia/package-class_visit`. Each is written against verified
code (file:line as of `v0.0.15` / `45d657f`), not against the issue text alone.

## Batch 1 — approved 2026-09-16

Ordered by risk, then by whether the fix stands alone. All six are shippable in one
release; there is no code dependency between them.

| # | Plan | Shape | Decisions open? |
|---|---|---|---|
| 10 | [install() must not overwrite a configured tenant](2026-09-16-10-install-non-destructive.md) | data-loss bug | no |
| 11 | [Save as Draft must skip required fields](2026-09-16-11-draft-skips-required.md) | bug | no |
| 13 | [Faculty letter download](2026-09-16-13-faculty-letter-download.md) | bug | no |
| 12 | [CE scheduling form parity](2026-09-16-12-ce-form-parity.md) | bug | one (edit-case carve-out) |
| 4 | [Report URL shortcodes](2026-09-16-04-report-url-shortcodes.md) | unfinished feature | **yes — read first** |
| 5 | [Office "report submitted" email](2026-09-16-05-office-submitted-email.md) | feature | **yes — defaults** |

Do #10 first regardless of anything else: until it ships, any tenant boot can wipe
the Class Visit configuration, including the settings the other five plans add.

## Batch 2 — approved 2026-09-16

| # | Plan | Shape | Decisions open? |
|---|---|---|---|
| 14 | [Instructor sign-off, response and attachments](2026-09-16-14-instructor-signoff.md) | feature (migration) | no |
| 9 | [Docs mismatches and dead code](2026-09-16-09-docs-and-dead-code.md) | docs + deletion | no |

**#14 supersedes #7** (acknowledgement/response) and absorbs **#9 part B** (attachments).
Close #7 when #14 ships.

#14 adds four settings keys, so it must land after #10 — see that plan.

## Batch 3

| # | Plan | Shape | Decisions open? |
|---|---|---|---|
| 8 | [Role-aware access and the faculty→teacher mapping](2026-09-16-08-role-and-teacher-scoped-access.md) | scoping change | no |

Land #13 and #12 first — #8 narrows the same faculty querysets.

Batch 3 also carries:

| # | Plan | Shape | Decisions open? |
|---|---|---|---|
| 6 | [Rubric report fields (narrow)](2026-09-16-06-rubric-report-fields.md) | field-engine feature | no |

Land #11 first — it touches the same ChoiceField blank-choice logic.

**Every open issue now has a plan.**

## Shipped ahead of the batches

The `edit_visit_report` authorization hole (no issue filed yet) — fixed in `02ca1e8`:
only a visit's `visitors`, or CE, may write its report.

## Found while planning, not yet filed

**`edit_visit_report` has no ownership check.** `views/faculty.py:190` does
`get_object_or_404(VisitSchedule, pk=visit_id)` and nothing else, and the URL guard
(`urls/faculty.py:28`) only requires *a* faculty role. So any faculty user can open
and edit any visit report in the tenant given its UUID — including writing a report on
another mentor's visit. Every other report path scopes by `CourseAdministrator`
(faculty), teacher (instructor) or CIS role (CE). This is a live authorization hole
and should outrank most of batch 1.

## Shipping (applies to every plan)

1. Commit in `webapp/class_visit` (separate git repo).
2. Bump `version` in **both** `setup.cfg` and `pyproject.toml` in the commit you tag —
   pip keys upgrades off that string, so a stale version means `pip install` keeps the
   old code with no error.
3. Tag, push the tag.
4. Bump each tenant's pin in `webapp/requirements.txt` and move its submodule pointer.

Tenants and their current pins: ewu `v0.0.15`, rvcc `v0.0.15`, tvcc `v0.0.15`,
lsco `v0.0.13`, sccc `v0.0.12`. Anything shipped only reaches a tenant whose pin moves;
lsco and sccc will jump several versions, so re-read their settings rows after upgrading
(see #10).

## Test conventions in this package

Tests live in `class_visit/tests/` and run as
`docker exec -w /app/webapp django_web_ewu python manage.py test class_visit`.
Patch targets must be built from `PKG` (resolved at runtime), never spelled out as
`class_visit.class_visit.…` — the suite ships in the wheel and runs in both the nested
(submodule) and flat (pip) layouts.

**Do not mock the ORM in these tests.** `tests/test_views_faculty.py:175-250` is the
cautionary case: it patches `VisitReport` and stubs
`objects.filter().distinct()`, so the id-type mismatch in #13 was invisible and the
test passed against code that could never work. Use real rows.
