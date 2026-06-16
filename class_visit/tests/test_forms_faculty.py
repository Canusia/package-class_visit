"""Tests for class_visit.class_visit.forms.faculty.

The VisitScheduleFormValidationTest suite uses a real test database so that
ClassSection.objects.filter(...).select_related(...) executes against actual
ORM querysets instead of plain-list mocks.  This removes the need for the
try/except AttributeError workaround that previously guarded those calls.
"""

from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in

from cis.models.term import AcademicYear, Term
from cis.models.course import Cohort, Course, CourseAdministrator
from cis.models.highschool import HighSchool
from cis.models.teacher import Teacher
from cis.models.section import ClassSection

from class_visit.class_visit.forms.faculty import VisitScheduleForm, VisitReportDynamicForm

User = get_user_model()

# ---------------------------------------------------------------------------
# Guard against django_login_history IP-requirement signal during test login
# ---------------------------------------------------------------------------
try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:
    _login_history_post_login = None


# ---------------------------------------------------------------------------
# Shared DB factory helpers
# ---------------------------------------------------------------------------

def _make_user(suffix):
    email = f"test_cvf_{suffix}@example.com"
    return User.objects.create_user(
        username=email,
        email=email,
        password="testpass",
        first_name="Test",
        last_name=f"User{suffix}",
    )


def _make_graph(suffix="a"):
    """Create the minimum object graph needed by VisitScheduleForm.

    Returns a dict with keys: faculty_user, teacher_user, teacher, course,
    term, highschool, section.
    """
    ay, _ = AcademicYear.objects.get_or_create(name=f"AY-CVF-{suffix}")
    term, _ = Term.objects.get_or_create(
        academic_year=ay,
        label=f"Fall-{suffix}",
        defaults={"code": f"F{suffix}"},
    )
    cohort, _ = Cohort.objects.get_or_create(
        name=f"CVF Cohort {suffix}",
        designator=f"CVFC{suffix}",
    )
    course, _ = Course.objects.get_or_create(
        catalog_number=f"CVF{suffix}01",
        cohort=cohort,
        defaults={"title": f"CVF Course {suffix}"},
    )
    highschool, _ = HighSchool.objects.get_or_create(
        name=f"CVF High School {suffix}",
        defaults={"code": f"CVFHS{suffix}"},
    )
    teacher_user = _make_user(f"teacher_{suffix}")
    teacher = Teacher.objects.create(user=teacher_user)

    section = ClassSection.objects.create(
        class_number=f"CVF-{suffix}-001",
        section_number="1",
        term=term,
        course=course,
        highschool=highschool,
        teacher=teacher,
        status="A",
    )

    faculty_user = _make_user(f"faculty_{suffix}")
    # Wire faculty_user as an active CourseAdministrator for the course
    CourseAdministrator.objects.create(
        user=faculty_user,
        course=course,
        status="Active",
    )

    return {
        "faculty_user": faculty_user,
        "teacher_user": teacher_user,
        "teacher": teacher,
        "course": course,
        "term": term,
        "highschool": highschool,
        "section": section,
    }


def _post_data(section_ids, visitor_ids,
               visit_date="06/20/2026", visit_type="Observation",
               pre_visit_note=""):
    return {
        "class_sections": section_ids,
        "visitors": visitor_ids,
        "visit_date": visit_date,
        "type_of_visit": visit_type,
        "pre_visit_note": pre_visit_note,
    }


# ---------------------------------------------------------------------------
# VisitScheduleForm — real-DB validation tests
# ---------------------------------------------------------------------------

_SETTINGS = {
    "section_status_filter": "active",
    "visit_types": "Observation|Evaluation",
    "notify_teacher_on_schedule": "No",
}


class VisitScheduleFormValidationTest(TestCase):
    """Form validators (same-teacher, not-needed, status) against real DB rows."""

    @classmethod
    def setUpClass(cls):
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    def _build_form(self, faculty_user, section_ids, visitor_ids):
        """Instantiate VisitScheduleForm with patched settings.

        Because VisitScheduleForm.__init__ builds choices from the DB and
        MultipleChoiceField validates submitted values against those choices,
        we inject the test section IDs into the choices list after __init__
        so that clean_class_sections() can run without a 'not a valid choice'
        error.  The visitor field is handled the same way.
        """
        with patch(
            "class_visit.class_visit.forms.faculty.ClassVisitSettings"
        ) as mock_settings:
            mock_settings.from_db.return_value = _SETTINGS
            form = VisitScheduleForm(
                faculty_user=faculty_user,
                data=_post_data(section_ids, visitor_ids),
            )
        # Expand choices so the submitted IDs are valid choices
        for sid in section_ids:
            if (sid, sid) not in form.fields["class_sections"].choices:
                form.fields["class_sections"].choices.append((sid, sid))
        for vid in visitor_ids:
            if (vid, vid) not in form.fields["visitors"].choices:
                form.fields["visitors"].choices.append((vid, vid))
        return form

    def test_valid_section_passes(self):
        """A real active section with one teacher passes all validators."""
        graph = _make_graph("v1")
        sec = graph["section"]
        faculty_user = graph["faculty_user"]

        form = self._build_form(
            faculty_user,
            [str(sec.id)],
            [str(faculty_user.id)],
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_mismatched_teachers_rejected(self):
        """Sections from different teachers must fail clean_class_sections."""
        graph_a = _make_graph("mm1")
        graph_b = _make_graph("mm2")

        # Both courses must be administered by the same faculty user
        faculty_user = graph_a["faculty_user"]
        CourseAdministrator.objects.create(
            user=faculty_user,
            course=graph_b["course"],
            status="Active",
        )

        sec_a = graph_a["section"]
        sec_b = graph_b["section"]

        form = self._build_form(
            faculty_user,
            [str(sec_a.id), str(sec_b.id)],
            [str(faculty_user.id)],
        )
        self.assertFalse(form.is_valid())
        self.assertIn("class_sections", form.errors)
        self.assertIn(
            "same instructor",
            "\n".join(form.errors["class_sections"]),
        )

    def test_not_needed_section_rejected(self):
        """A section with a NotNeededVisit row must be rejected."""
        from class_visit.class_visit.models import NotNeededVisit

        graph = _make_graph("nn1")
        sec = graph["section"]
        faculty_user = graph["faculty_user"]

        NotNeededVisit.objects.create(class_section=sec)

        form = self._build_form(
            faculty_user,
            [str(sec.id)],
            [str(faculty_user.id)],
        )
        self.assertFalse(form.is_valid())
        self.assertIn("class_sections", form.errors)
        self.assertIn(
            "not needing a visit",
            "\n".join(form.errors["class_sections"]),
        )

    def test_wrong_status_section_rejected(self):
        """A Cancelled section (status='C') must fail when filter=active."""
        graph = _make_graph("ws1")
        sec = graph["section"]
        faculty_user = graph["faculty_user"]

        # Flip to Cancelled
        sec.status = "C"
        sec.save()

        form = self._build_form(
            faculty_user,
            [str(sec.id)],
            [str(faculty_user.id)],
        )
        self.assertFalse(form.is_valid())
        self.assertIn("class_sections", form.errors)
        self.assertIn(
            "ineligible status",
            "\n".join(form.errors["class_sections"]),
        )


# ---------------------------------------------------------------------------
# VisitReportDynamicForm — no DB access needed; mocks are fine here
# ---------------------------------------------------------------------------

class VisitReportDynamicFormTest(TestCase):

    @patch("class_visit.class_visit.forms.faculty.report_fields")
    def test_form_builds_fields_from_service(self, mock_rf):
        mock_rf.build_report_form_fields.return_value = {}
        visit = MagicMock()
        form = VisitReportDynamicForm(visit=visit, initial_meta=None)
        mock_rf.build_report_form_fields.assert_called_once_with(initial=None)

    @patch("class_visit.class_visit.forms.faculty.report_fields")
    def test_form_builds_fields_with_existing_meta(self, mock_rf):
        existing_meta = {"field_a": "value"}
        mock_rf.build_report_form_fields.return_value = {}
        visit = MagicMock()
        form = VisitReportDynamicForm(visit=visit, initial_meta=existing_meta)
        mock_rf.build_report_form_fields.assert_called_once_with(initial=existing_meta)
