"""Only the visit's own visitors (or CE staff) may open or write a visit report.

`edit_visit_report` used to do `get_object_or_404(VisitSchedule, pk=visit_id)` and
nothing else, while the URL guard only required *a* faculty role. Any faculty user
could therefore open — and submit — a report on any visit in the tenant given its UUID,
including writing a report on another mentor's visit.

Being a CourseAdministrator for the course is deliberately NOT enough: it puts the visit
in your list, so you can see that it exists, but the report is the visitor's own account
of a class they attended.
"""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import Client, TestCase
from django.urls import reverse

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.course import Cohort, Course, CourseAdministrator
from cis.models.section import ClassSection
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from ..models import VisitSchedule

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


def _faculty_user(**extra):
    user = User.objects.create_user(
        username=f'fac_{_sfx()}', email=f'fac_{_sfx()}@x.com', password='x', **extra)
    user.groups.add(Group.objects.get_or_create(name='faculty')[0])
    return user


class EditVisitReportAuthzTest(TestCase):
    @classmethod
    def setUpClass(cls):
        # django_login_history's post_login receiver crashes on the test client's
        # missing REMOTE_ADDR.
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    def setUp(self):
        self.client = Client(REMOTE_ADDR='127.0.0.1')

    @classmethod
    def setUpTestData(cls):
        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        cls.course = Course.objects.create(
            catalog_number='101', title='A', cohort=cohort)
        teacher = Teacher.objects.create(user=User.objects.create_user(
            username=f't_{_sfx()}', email=f't_{_sfx()}@x.com', password='x'))
        section = ClassSection.objects.create(
            course=cls.course, term=term, teacher=teacher,
            class_number=f'C-{_sfx()}', section_number='001')

        cls.visitor = _faculty_user()
        cls.other_faculty = _faculty_user()
        # Administers the course, but is not a visitor on this visit.
        cls.course_admin = _faculty_user()
        CourseAdministrator.objects.create(
            user=cls.course_admin, course=cls.course, role='Faculty', status='Active')

        cls.ce_user = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')
        cls.ce_user.groups.add(Group.objects.get_or_create(name='ce')[0])

        cls.visit = VisitSchedule.objects.create(
            visit_date='2026-03-01', type_of_visit='Initial', meta={})
        cls.visit.class_sections.add(section)
        cls.visit.visitors.add(cls.visitor)

    def _url(self, visit=None):
        return reverse('faculty_class_visit:edit_visit_report',
                       kwargs={'visit_id': (visit or self.visit).id})

    def test_visitor_may_open_the_report(self):
        self.client.force_login(self.visitor)
        self.assertEqual(self.client.get(self._url()).status_code, 200)

    def test_ce_staff_may_open_the_report(self):
        self.client.force_login(self.ce_user)
        self.assertEqual(self.client.get(self._url()).status_code, 200)

    def test_unrelated_faculty_is_refused(self):
        self.client.force_login(self.other_faculty)
        self.assertEqual(self.client.get(self._url()).status_code, 404)

    def test_course_administrator_who_is_not_a_visitor_is_refused(self):
        self.client.force_login(self.course_admin)
        self.assertEqual(self.client.get(self._url()).status_code, 404)

    def test_unrelated_faculty_cannot_post_a_report(self):
        self.client.force_login(self.other_faculty)
        resp = self.client.post(self._url(), {'submit_action': 'submit'})
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(hasattr(self.visit, 'report') and self.visit.report.pk)

    def test_anonymous_is_redirected(self):
        resp = self.client.get(self._url())
        self.assertIn(resp.status_code, (301, 302))
