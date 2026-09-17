"""Who may see and schedule class visits, and for which sections (#8).

Two rules, in one place because every faculty scoping site needs both.

**Role.** Access follows the CourseAdministrator role, not merely the existence
of a row: Faculty, Visitor, Dept. Chair and Dean take part in class visits;
Administrator and FC Reviewer do not. Note that Administrator remains the
*notification* target for the office "report submitted" email -- access and
notification use the same vocabulary for different purposes, deliberately.

**Instructors.** Scoping used to stop at "courses I administer" and ignore
cis's faculty->teacher mapping (FacultyTeacherAssignment), so "Dr. Smith is
responsible for these three instructors this year" had no effect here.

The mapping is applied per section, keyed on the *section's* academic year, and
deliberately not through ``cis.services.faculty_scope.visible_teachers``:

- that function falls back to teachers holding a TeacherCourseCertificate, but
  this app never required one -- routing through it would silently hide
  sections whose instructor lacks a certificate on a tenant that configured
  nothing;
- it resolves a single (active) academic year, so this year's assignments would
  hide last year's visits.

So: a section is in scope if its course is, and either no assignment rows exist
for (user, course, section's year) or the section's teacher is assigned. With
no rows configured that is exactly the old course-only behaviour.

On a cis without FacultyTeacherAssignment (package-cis < v0.0.20) the mapping does not
exist, so the second rule is skipped and scoping is course-only.
"""
from django.db.models import Exists, OuterRef

from cis.models.course import CourseAdministrator
from cis.models.section import ClassSection

try:
    from cis.models.faculty import FacultyTeacherAssignment
except ImportError:
    # package-cis < v0.0.20 (or an in-tree cis that predates migration 0078) has no
    # faculty->teacher mapping; scoping is then course-only, same as a tenant that
    # configured no assignment rows.
    FacultyTeacherAssignment = None

#: CourseAdministrator roles that take part in class visits.
CLASS_VISIT_ROLES = ('Faculty', 'Visitor', 'Dept. Chair', 'Dean')


def scoped_course_ids(user):
    """Course ids this user administers in a class-visit role."""
    return CourseAdministrator.objects.filter(
        user=user,
        status__iexact='active',
        role__in=CLASS_VISIT_ROLES,
    ).values_list('course__id', flat=True)


def scoped_sections(user):
    """ClassSections this user may see, per role and the faculty->teacher map."""
    sections = ClassSection.objects.filter(course__id__in=scoped_course_ids(user))
    if FacultyTeacherAssignment is None:
        return sections

    year_assignments = FacultyTeacherAssignment.objects.filter(
        user=user,
        course_id=OuterRef('course_id'),
        academic_year_id=OuterRef('term__academic_year_id'),
    )
    return sections.filter(
        ~Exists(year_assignments)
        | Exists(year_assignments.filter(teacher_id=OuterRef('teacher_id')))
    )


def class_visit_administrators(course_ids):
    """Active CourseAdministrator rows eligible to be named as visitors."""
    return CourseAdministrator.objects.filter(
        course__id__in=course_ids,
        status__iexact='active',
        role__in=CLASS_VISIT_ROLES,
    )
