# #8 — Role-aware access and the faculty→teacher mapping

The issue is titled "no department-scoped access for deans and chairs", but there is no
department walk to build: deans and chairs are already `CourseAdministrator` rows,
distinguished by `role`. Two real gaps sit underneath it.

## Decisions taken

1. **Four roles get class-visit access:** `Faculty`, `Visitor`, `Dept. Chair`, `Dean`.
   `Administrator` and `FC Reviewer` play no part in class visits and are excluded.
2. **One scope rule for both viewing and scheduling**, based on the faculty→teacher
   mapping: a user sees the visits and reports of the **instructors visible to them**, and
   schedules visits within that same set. Not "every report in the tenant", not "every
   report on the course".

## What exists already

- `CourseAdministrator.ROLE_OPTIONS` (`cis/models/course.py:788-795`):
  `Administrator`, `Faculty`, `FC Reviewer`, `Visitor`, `Dept. Chair`, `Dean`.
  On ewu dev all 108 rows are `Faculty`; the other roles are configured but unused so far.
- **`cis.services.faculty_scope.visible_teachers(user, academic_year=None)`** — the
  platform's faculty→teacher mapping, backed by
  `cis.models.faculty.FacultyTeacherAssignment` grained
  `(user, course, teacher, academic_year)`. Absence of rows for a course means "fall back
  to every certified teacher for it", so a half-finished configuration over-shows rather
  than hiding instructors with nothing on screen to explain why. It has a tenant override
  seam (`get_tenant_override('faculty_scope', …)`), and tenant modules must re-export
  `default_visible_teachers`, not the wrapper.
- **class_visit does not use any of it.** `grep` for `faculty_scope`, `visible_teachers`
  or `FacultyTeacherAssignment` across the package returns nothing.

## The six scoping sites (all the same shape today)

Every one runs `CourseAdministrator.objects.filter(user=…, status__iexact='active')` and
takes **every** course, ignoring `role`, and then every section of those courses,
ignoring the teacher mapping and the academic year:

| Site | What it scopes |
|---|---|
| `views/faculty.py:60` | schedulable sections feed (`FacultySchedulableSectionViewSet`) |
| `views/faculty.py:96` | the visits list feed (`FacultyVisitScheduleViewSet`) |
| `views/faculty.py:278` | bulk letter export (the security scope for #13) |
| `views/faculty.py:322` | index page filter dropdowns (courses) |
| `views/faculty.py:329` | index page filter dropdowns (visitors) |
| `forms/faculty.py:94, 138` | section choices and visitor choices on the scheduling form |

`views/faculty.py:190` (report editing) is already correct as of `02ca1e8`: it keys on the
visit's `visitors` M2M, not on `CourseAdministrator`.

## Fix

**1. One shared scope helper**, e.g. `services/scope.py`:

```python
CLASS_VISIT_ROLES = ('Faculty', 'Visitor', 'Dept. Chair', 'Dean')

def scoped_course_ids(user):
    return CourseAdministrator.objects.filter(
        user=user, status__iexact='active', role__in=CLASS_VISIT_ROLES,
    ).values_list('course__id', flat=True)

def scoped_teacher_ids(user, academic_year=None):
    from cis.services.faculty_scope import visible_teachers
    return visible_teachers(user, academic_year).values_list('id', flat=True)
```

Import `visible_teachers` **inside** the function, not at module level: the tenant's
`services/faculty_scope.py` imports `cis.models.*` at its own module level, so resolving
it during import risks `AppRegistryNotReady` — the same reasoning `cis` documents for
`_tenant_faculty_scope_override`.

**2. Narrow all six sites** to courses from `scoped_course_ids` **and** sections whose
teacher is in `scoped_teacher_ids`. Sections carry `teacher` directly
(`ClassSection.teacher`), so this is one extra `teacher_id__in=…` clause, not a join walk.

**3. Guard against the `cis` floor.** `visible_teachers` arrived in `cis` v0.0.20. A tenant
pinned below that has no such module, and `class_visit` does not declare a `cis`
dependency. Either declare one (`myce_cis>=0.0.20` — the shape `cis` itself now uses for
`student_onboarding`), or `find_spec`-guard the import and fall back to the current
course-only scope. Declaring the floor is honest; the fallback hides a downgrade. Prefer
the floor, and say so in the release notes.

**4. Leave CE alone.** `views/ce.py` has no user scoping by design — CE sees everything.

## Upgrade risk — check before shipping

Today **every** role has full faculty access. After this change, `Administrator` and
`FC Reviewer` rows lose it. On ewu that is invisible (all rows are `Faculty`), but the
other four tenants pin this package and may rely on it. Before release, run per tenant:

```
CourseAdministrator.objects.values('role').annotate(n=Count('id')).order_by('-n')
```

If a tenant has `Administrator` rows whose users actually use class visits, they need
their role changed (data fix) or the role list needs to be a setting. Do not discover this
after the pin moves.

The teacher-mapping narrowing is safe by construction: with no `FacultyTeacherAssignment`
rows, `visible_teachers` returns the full certified list, i.e. today's behaviour.

## Tests (`class_visit/tests/test_faculty_scope.py`, new)

1. Each of the four allowed roles reaches the visits feed and the schedulable-sections
   feed; `Administrator` and `FC Reviewer` get an empty scope.
2. A user with no `CourseAdministrator` row sees nothing (unchanged).
3. With no `FacultyTeacherAssignment` rows, a faculty user sees every certified teacher's
   sections — byte-for-byte today's list. This is the "over-show rather than hide"
   guarantee and the main regression risk.
4. With assignment rows for (user, course, year), only the assigned teachers' sections and
   visits appear; a sibling teacher's visit on the same course is excluded.
5. Assignments for a *different* academic year do not narrow the current year.
6. The bulk-export scope (`views/faculty.py:278`) refuses a visit outside the narrowed
   set — pairs with #13's tests.
7. The scheduling form's section and visitor choices honour the same rule.
8. A dean and a chair can schedule a visit and view a report for an instructor in scope,
   and cannot for one outside it.
9. CE is unaffected: a CE user still sees every visit.

## Sequencing

Independent of batches 1 and 2, but it touches the same faculty queryset as #13 (bulk
export) and #12 (form choices). Land those first and this becomes a narrowing of code that
is already correct, rather than two edits racing on the same lines.
