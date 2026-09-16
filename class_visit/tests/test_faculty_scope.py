"""Class-visit access is role-aware and honours the faculty->teacher mapping (#8).

Two gaps sat under "no department-scoped access for deans and chairs":

1. Every CourseAdministrator row granted full faculty capability, whatever its role.
   Access is now limited to Faculty, Visitor, Dept. Chair and Dean; Administrator and
   FC Reviewer play no part in class visits.
2. Scoping stopped at "courses I administer" and ignored cis's faculty->teacher mapping
   (FacultyTeacherAssignment via faculty_scope.visible_teachers), so "Dr. Smith is
   responsible for these three instructors this year" had no effect here.

The safety property worth guarding: with no assignment rows configured,
visible_teachers returns every certified teacher, so a tenant that configures nothing
sees exactly what it saw before.
"""
import datetime
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import Client, TestCase
from django.urls import reverse

from cis.models.course import Cohort, Course, CourseAdministrator
from cis.models.faculty import FacultyTeacherAssignment
from cis.models.section import ClassSection
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from ..models import VisitSchedule

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class FacultyScopeTest(TestCase):
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

    @classmethod
    def setUpTestData(cls):
        cls.ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        cls.term = Term.objects.create(
            academic_year=cls.ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        cls.course = Course.objects.create(
            catalog_number='101', title='A', cohort=cohort)

        cls.teacher_a = cls._teacher()
        cls.teacher_b = cls._teacher()
        cls.section_a = cls._section(cls.teacher_a, '001')
        cls.section_b = cls._section(cls.teacher_b, '002')

        cls.visit_a = cls._visit(cls.section_a)
        cls.visit_b = cls._visit(cls.section_b)

    @classmethod
    def _teacher(cls):
        return Teacher.objects.create(user=User.objects.create_user(
            username=f't_{_sfx()}', email=f't_{_sfx()}@x.com', password='x'))

    @classmethod
    def _section(cls, teacher, number):
        return ClassSection.objects.create(
            course=cls.course, term=cls.term, teacher=teacher,
            class_number=f'C-{_sfx()}', section_number=number, status='A')

    @classmethod
    def _visit(cls, section):
        visit = VisitSchedule.objects.create(
            visit_date=datetime.date(2026, 3, 1), type_of_visit='Initial', meta={})
        visit.class_sections.add(section)
        return visit

    def _user_with_role(self, role):
        user = User.objects.create_user(
            username=f'u_{_sfx()}', email=f'u_{_sfx()}@x.com', password='x')
        user.groups.add(Group.objects.get_or_create(name='faculty')[0])
        CourseAdministrator.objects.create(
            user=user, course=self.course, role=role, status='Active')
        return user

    def _visit_ids(self, user):
        client = Client(REMOTE_ADDR='127.0.0.1')
        client.force_login(user)
        resp = client.get(
            '/faculty/class_visits/api/visit_schedule/?format=json')
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        rows = resp.json()
        rows = rows['results'] if isinstance(rows, dict) else rows
        return {row['id'] for row in rows}

    # -- role filter ---------------------------------------------------------

    def test_the_four_class_visit_roles_have_access(self):
        for role in ('Faculty', 'Visitor', 'Dept. Chair', 'Dean'):
            with self.subTest(role=role):
                ids = self._visit_ids(self._user_with_role(role))
                self.assertIn(str(self.visit_a.id), ids)

    def test_administrator_and_fc_reviewer_have_no_class_visit_access(self):
        for role in ('Administrator', 'FC Reviewer'):
            with self.subTest(role=role):
                self.assertEqual(self._visit_ids(self._user_with_role(role)), set())

    def test_a_user_with_no_course_administrator_row_sees_nothing(self):
        user = User.objects.create_user(
            username=f'u_{_sfx()}', email=f'u_{_sfx()}@x.com', password='x')
        user.groups.add(Group.objects.get_or_create(name='faculty')[0])

        self.assertEqual(self._visit_ids(user), set())

    # -- the faculty -> teacher mapping --------------------------------------

    def test_unconfigured_tenant_sees_every_teachers_visits(self):
        """The safety property: no FacultyTeacherAssignment rows means exactly the
        old course-only scope -- including teachers with no TeacherCourseCertificate,
        which is why this does not go through cis's visible_teachers."""
        ids = self._visit_ids(self._user_with_role('Faculty'))

        self.assertIn(str(self.visit_a.id), ids)
        self.assertIn(str(self.visit_b.id), ids)

    def test_assignments_narrow_to_the_assigned_teachers(self):
        user = self._user_with_role('Dept. Chair')
        FacultyTeacherAssignment.objects.create(
            user=user, course=self.course, teacher=self.teacher_a,
            academic_year=self.ay)

        ids = self._visit_ids(user)

        self.assertIn(str(self.visit_a.id), ids)
        self.assertNotIn(str(self.visit_b.id), ids)

    def test_assignments_for_another_year_do_not_narrow_this_one(self):
        user = self._user_with_role('Faculty')
        other_year = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        FacultyTeacherAssignment.objects.create(
            user=user, course=self.course, teacher=self.teacher_a,
            academic_year=other_year)

        ids = self._visit_ids(user)

        self.assertIn(str(self.visit_b.id), ids)

    def test_assignments_narrow_only_their_own_year(self):
        """This year's assignments must not hide last year's visits."""
        user = self._user_with_role('Faculty')
        last_year = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        old_term = Term.objects.create(
            academic_year=last_year, code='SP', label=f'Spring-{_sfx()}')
        old_section = ClassSection.objects.create(
            course=self.course, term=old_term, teacher=self.teacher_b,
            class_number=f'C-{_sfx()}', section_number='003', status='A')
        old_visit = self._visit(old_section)
        FacultyTeacherAssignment.objects.create(
            user=user, course=self.course, teacher=self.teacher_a,
            academic_year=self.ay)

        ids = self._visit_ids(user)

        self.assertIn(str(old_visit.id), ids)
        self.assertNotIn(str(self.visit_b.id), ids)

    # -- the same rule applies to the other scoping sites --------------------

    def test_bulk_export_refuses_a_visit_outside_the_narrowed_scope(self):
        from unittest.mock import patch

        from . import PKG

        user = self._user_with_role('Faculty')
        FacultyTeacherAssignment.objects.create(
            user=user, course=self.course, teacher=self.teacher_a,
            academic_year=self.ay)
        from ..models import VisitReport
        VisitReport.objects.create(
            visit_schedule=self.visit_b, status='Submitted', meta={})

        client = Client(REMOTE_ADDR='127.0.0.1')
        client.force_login(user)
        with patch(f'{PKG}.views.faculty.pdf_service.visit_letters_pdf') as mock_pdf:
            resp = client.post(reverse('faculty_class_visit:bulk_action'), {
                'action': 'export_pdf', 'public_only': '0',
                'ids[]': [str(self.visit_b.id)]})

        self.assertEqual(resp.status_code, 404)
        mock_pdf.assert_not_called()

    def test_schedulable_sections_honour_the_mapping(self):
        user = self._user_with_role('Dean')
        FacultyTeacherAssignment.objects.create(
            user=user, course=self.course, teacher=self.teacher_a,
            academic_year=self.ay)

        client = Client(REMOTE_ADDR='127.0.0.1')
        client.force_login(user)
        resp = client.get('/faculty/class_visits/api/class_sections/?format=json')

        self.assertEqual(resp.status_code, 200, resp.content[:200])
        rows = resp.json()
        rows = rows['results'] if isinstance(rows, dict) else rows
        ids = {row['id'] for row in rows}
        self.assertIn(str(self.section_a.id), ids)
        self.assertNotIn(str(self.section_b.id), ids)

    def test_manage_visit_404s_for_a_section_outside_scope(self):
        user = self._user_with_role('Faculty')
        FacultyTeacherAssignment.objects.create(
            user=user, course=self.course, teacher=self.teacher_a,
            academic_year=self.ay)

        client = Client(REMOTE_ADDR='127.0.0.1')
        client.force_login(user)
        in_scope = client.get(reverse(
            'faculty_class_visit:manage_visit',
            kwargs={'class_section_id': self.section_a.id}))
        out_of_scope = client.get(reverse(
            'faculty_class_visit:manage_visit',
            kwargs={'class_section_id': self.section_b.id}))

        self.assertEqual(in_scope.status_code, 200)
        self.assertEqual(out_of_scope.status_code, 404)
