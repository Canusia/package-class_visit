"""CE schedules a visit on behalf of a section's faculty / visitor (#18).

Visitor eligibility must match the faculty form (active CourseAdministrators in
CLASS_VISIT_ROLES), the visit records that CE scheduled it, and CE has an entry
point on /ce/class_visits/ to start scheduling for any section.
"""
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.course import Cohort, Course, CourseAdministrator
from cis.models.section import ClassSection
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from . import PKG
from ..forms.ce import CEVisitScheduleForm
from ..models import NotNeededVisit, VisitSchedule

User = get_user_model()
SETTINGS = {'section_status_filter': 'active', 'visit_types': 'Initial|Follow-up'}


def _sfx():
    return uuid.uuid4().hex[:8]


def _user(first, last, group=None):
    u = User.objects.create_user(
        username=f'{first}_{_sfx()}', email=f'{first}_{_sfx()}@x.com', password='x',
        first_name=first, last_name=last)
    if group:
        u.groups.add(Group.objects.get_or_create(name=group)[0])
    return u


class _Fixture(TestCase):
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
        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        cls.term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        cls.course = Course.objects.create(catalog_number='101', title='A', cohort=cohort)
        cls.teacher = Teacher.objects.create(user=_user('Tess', 'Teacher'))
        cls.section = cls._section('001', 'A')

        cls.faculty = _user('Fay', 'Faculty', 'faculty')
        cls.chair = _user('Cher', 'Chair', 'faculty')
        cls.inactive = _user('Ina', 'Inactive', 'faculty')
        cls.coordinator = _user('Cora', 'Coordinator', 'faculty')
        for user, role, status in (
                (cls.faculty, 'Faculty', 'Active'),
                (cls.faculty, 'Dept. Chair', 'Active'),  # second row: listed once
                (cls.chair, 'Dept. Chair', 'Active'),
                (cls.inactive, 'Faculty', 'Inactive'),
                (cls.coordinator, 'Coordinator', 'Active')):
            CourseAdministrator.objects.create(
                user=user, course=cls.course, role=role, status=status)

        cls.ce_user = _user('Cece', 'Staff', 'ce')

    @classmethod
    def _section(cls, number, status):
        return ClassSection.objects.create(
            course=cls.course, term=cls.term, teacher=cls.teacher,
            class_number=f'C-{_sfx()}', section_number=number, status=status)

    def _form(self, visit_id=None, data=None):
        with patch(f'{PKG}.forms.ce.ClassVisitSettings.from_db', return_value=SETTINGS):
            return CEVisitScheduleForm(
                section_id=self.section.id, visit_id=visit_id, data=data)


class VisitorEligibilityTest(_Fixture):
    def _visitor_values(self, visit_id=None):
        return [v for v, _ in self._form(visit_id).fields['visitors'].choices]

    def test_lists_active_class_visit_roles_once(self):
        values = self._visitor_values()
        self.assertEqual(values.count(str(self.faculty.id)), 1)
        self.assertIn(str(self.chair.id), values)

    def test_excludes_inactive_and_non_visit_roles(self):
        values = self._visitor_values()
        self.assertNotIn(str(self.inactive.id), values)
        self.assertNotIn(str(self.coordinator.id), values)

    def test_edit_keeps_existing_ineligible_visitor(self):
        visit = VisitSchedule.objects.create(
            visit_date='2026-03-01', type_of_visit='Initial', meta={})
        visit.class_sections.add(self.section)
        visit.visitors.add(self.inactive)

        form = self._form(visit_id=visit.id)
        labels = dict(form.fields['visitors'].choices)
        self.assertIn(str(self.inactive.id), labels)
        self.assertIn('currently scheduled', str(labels[str(self.inactive.id)]))
        self.assertIn(str(self.inactive.id), form.fields['visitors'].initial)


class OnBehalfAuditTest(_Fixture):
    def _request(self):
        request = RequestFactory().post('/')
        request.user = self.ce_user
        return request

    def _save(self, visit_id='-1'):
        form = self._form(visit_id=None if visit_id == '-1' else visit_id, data={
            'class_sections': [str(self.section.id)],
            'visitors': [str(self.faculty.id)],
            'visit_date': '2026-03-01',
            'type_of_visit': 'Initial',
            'visit_id': visit_id,
        })
        self.assertTrue(form.is_valid(), form.errors)
        with patch(f'{PKG}.forms.ce.ClassVisitSettings.from_db', return_value=SETTINGS):
            return form.save(request=self._request())

    def test_ce_create_records_scheduler(self):
        visit = self._save()
        self.assertEqual(visit.meta['scheduled_via'], 'ce')
        self.assertEqual(visit.meta['scheduled_by_id'], self.ce_user.pk)
        self.assertEqual(visit.scheduled_by_display, 'Cece Staff (CE)')

    def test_edit_does_not_overwrite_scheduler(self):
        visit = self._save()
        visit.meta['scheduled_by'] = 'Original'
        visit.save()
        self._save(visit_id=str(visit.id))
        visit.refresh_from_db()
        self.assertEqual(visit.meta['scheduled_by'], 'Original')

    def test_faculty_create_records_faculty(self):
        from ..forms.faculty import VisitScheduleForm
        with patch(f'{PKG}.forms.faculty.scoped_course_ids', return_value=[self.course.id]), \
                patch(f'{PKG}.forms.faculty.scoped_sections',
                      return_value=ClassSection.objects.filter(pk=self.section.pk)), \
                patch(f'{PKG}.forms.faculty.ClassVisitSettings.from_db', return_value=SETTINGS):
            form = VisitScheduleForm(self.faculty, data={
                'class_sections': [str(self.section.id)],
                'visitors': [str(self.faculty.id)],
                'visit_date': '03/01/2026',
                'type_of_visit': 'Initial',
            })
            self.assertTrue(form.is_valid(), form.errors)
            visit = form.save()
        self.assertEqual(visit.meta['scheduled_via'], 'faculty')
        self.assertEqual(visit.meta['scheduled_by_id'], self.faculty.pk)

    def test_ce_report_page_shows_scheduler(self):
        visit = self._save()
        self.client.force_login(self.ce_user)
        html = self.client.get(reverse(
            'class_visit:ce_view_report', kwargs={'visit_id': visit.id})).content.decode()
        self.assertIn('Scheduled By', html)
        self.assertIn('Cece Staff (CE)', html)

    def test_ce_scheduled_visit_reaches_visitor_portal(self):
        visit = self._save()
        self.client.force_login(self.faculty)
        resp = self.client.get(
            '/faculty/class_visits/api/visit_schedule/?format=datatables'
            '&draw=1&start=0&length=50')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(str(visit.id), resp.content.decode())


class SchedulePickerTest(_Fixture):
    def setUp(self):
        self.client = Client(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.ce_user)

    def _html(self, **params):
        with patch(f'{PKG}.views.ce.ClassVisitSettings.from_db', return_value=SETTINGS):
            return self.client.get(
                reverse('class_visit:ce_schedule_picker'), params).content.decode()

    @patch(f'{PKG}.views.ce.active_term', return_value=None)
    def test_index_has_schedule_button(self, _at):
        html = self.client.get(reverse('class_visit:ce_index')).content.decode()
        self.assertIn('Schedule a Visit', html)
        self.assertIn(reverse('class_visit:ce_schedule_picker'), html)

    def test_picker_links_eligible_section_to_manage_visit(self):
        html = self._html(term_id=self.term.id)
        self.assertIn(
            reverse('class_visit:ce_manage_visit', kwargs={'section_id': self.section.id}),
            html)

    def test_picker_excludes_not_needed_and_filtered_status(self):
        nn = self._section('002', 'A')
        NotNeededVisit.objects.create(class_section=nn)
        cancelled = self._section('003', 'C')
        html = self._html(term_id=self.term.id)
        self.assertNotIn(str(nn.id), html)
        self.assertNotIn(str(cancelled.id), html)

    def test_picker_honours_course_filter(self):
        other_course = Course.objects.create(
            catalog_number='202', title='B', cohort=self.course.cohort)
        html = self._html(course_id=other_course.id)
        self.assertNotIn(str(self.section.id), html)

    def test_non_ce_user_refused(self):
        self.client.force_login(self.faculty)
        resp = self.client.get(reverse('class_visit:ce_schedule_picker'))
        self.assertNotEqual(resp.status_code, 200)
