# #9 — Docs/code mismatches and dead code

Three unrelated pieces. Part B is now handled by
[#14](2026-09-16-14-instructor-signoff.md) and is not repeated here.

## Part A — three workbook questions the module cannot honour (docs fix, no code)

`docs/class-visit-configuration-workbook.md` asks three questions whose answers are fixed
in code. **Decision: the current behaviour is the intended behaviour**, so the questions
go away rather than becoming settings.

| Workbook | Question | Resolution |
|---|---|---|
| §1.1 | Who schedules visits — CE / faculty / both? | Both, always. Replace the question with a statement of fact. A deployment that truly wants one side drops the URL include; that is a deployment choice, not configuration. |
| §2.2 | Is a visit type required or optional? | Always required (`forms/ce.py`, `forms/faculty.py` both declare `type_of_visit` with `required=True`). Replace with a statement. |
| §3.2 | Do you want the "visit not needed" exemption feature? | Always on — CE staff need it. The tab renders unconditionally in `templates/class_visit/ce/index.html`. Replace with a statement, and document what the feature does instead of asking whether to enable it. |

Same edit in `docs/class-visit-native-capabilities.md` wherever it implies these are
configurable. No code change, no setting, no test — this is a documentation correction,
and its value is that an implementer stops promising a lever that does not exist.

## Part C — dead code removal

### What is actually dead

A repo-wide reference check (`cis/templates`, `myce_tenant_configs`, this package):

| File / symbol | Verdict |
|---|---|
| `templates/schedule/index.html` | dead — no view renders it, no template includes it. Uses the broken `ce_url`. |
| `templates/schedule/faculty/visits.html` | dead — same. Uses the broken `ce_url`. |
| `templates/schedule/manage_visit.html` | dead — zero references |
| `templates/schedule/manage_visit_report.html` | dead — zero references |
| `templates/schedule/edit_visit_report.html` | dead — zero references |
| `forms/__init__.py` (342 lines) | dead — no view imports it (`views/ce.py` imports `forms.ce`, `views/faculty.py` imports `forms.faculty`). It is the only creator of `VisitReportFile`, which #14 replaces properly. |
| `VisitSchedule.ce_url` (`models.py:309`) | dead — reverses `class_visit:edit_visit`, a name that does not exist (`urls/ce.py` defines `ce_edit_visit`). Only consumed by the two dead templates. |
| `VisitSchedule.visit_report_faculty_url` (`models.py:227`) | dead — and its two branches are identical, returning the same reverse either way |
| `VisitScheduleSerializer` / `ClassSectionVisitSerializer` `ce_url`, `visit_report_faculty_url`, `delete_url` fields (`serializers/__init__.py:39-66, 118-167`) | dead — no live viewset uses either serializer; CE/faculty/instructor each have their own |

The `reverse_lazy` in `ce_url` sits inside a `try/except` that can never fire: laziness
defers the `NoReverseMatch` until the value is rendered, long after the `except`.

### What must NOT be deleted

**`templates/schedule/class_visits.html` is live and load-bearing.** It is the embedded
visits table included from **seven** CE detail-page tabs in `cis` itself — class section,
teacher, course, term, academic year, high school, faculty coordinator
(`cis/templates/cis/{sections,teachers,course,term,term/academic_year,highschools,faculty}/tabs/_visits.html`)
— so it ships to every tenant. It uses the current CE contract (`ce_report_url`,
`class_visit:ce_manage_visit`), not the broken names, and
`tests/test_embedded_visits_tab.py` exists to pin it. Its directory being named
`schedule/` is historical, not a sign of deadness.

`VisitSchedule.delete_url` (`models.py:245`) also stays: the live faculty template reads
`row.delete_url` (`templates/class_visit/faculty/visits.html:247`), served by
`serializers/faculty.py:144`'s own method field.

### Steps

1. Delete the five dead templates, `forms/__init__.py`, the two dead model properties and
   the dead serializer fields. If removing `forms/__init__.py` entirely breaks the package
   import, leave an empty module rather than re-adding content.
2. Delete `VisitScheduleSerializer` and `ClassSectionVisitSerializer` outright if nothing
   else imports them; otherwise strip only the dead fields and say why they survive.
3. Run the suite. `tests/test_ce.py:618` and `tests/test_embedded_visits_tab.py` render
   `schedule/class_visits.html` — they must still pass untouched. That is the regression
   signal for having deleted the wrong thing.
4. The second half of the issue's "dead route names" — tenant menus pointing at the
   renamed `class_visit:visits` — is already handled defensively by migration
   `0008_add_class_visit_menu_items.py:68-69`. Confirm and close, no change.

### Tests

No new behaviour, so no new tests. The guard is the existing suite plus one addition:
a reference test asserting `schedule/class_visits.html` renders with the CE serializer
contract (already `test_embedded_visits_tab.py`) — extend its docstring to say the
sibling templates were deleted deliberately and this one is live, so the next reader does
not "finish the job".

## Suggested issue hygiene

Split on close: this plan covers A and C; B ships with #14. Comment on #9 with the three
outcomes rather than closing it silently, since each part lands in a different commit.
