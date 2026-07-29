"""The embedded visits partial (`schedule/class_visits.html`).

Host tenants include this partial from seven CE detail-page tabs (class
section, teacher, course, term, academic year, high school, faculty
coordinator). It is include-only — no view renders it — so a stale URL name
or serializer field inside it only surfaces as a 500 on the tab itself.

These tests pin the partial to the CE URL/serializer contract that
`urls/ce.py` + `serializers/ce.py` actually expose, and pin the two scoping
filters the tabs depend on (`class_section_id`, `academic_year_id`).
"""
import uuid
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase

from cis.models.course import Cohort, Course
from cis.models.section import ClassSection
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from class_visit.class_visit.models import VisitSchedule
from class_visit.class_visit.views.ce import CEVisitScheduleViewSet

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


def _render(**ctx):
    return render_to_string('schedule/class_visits.html', ctx)


class EmbeddedVisitsPartialTest(SimpleTestCase):
    """The partial must reverse and reference only names that exist today."""

    def setUp(self):
        self.record = SimpleNamespace(id=uuid.uuid4())

    def test_renders_add_button_with_ce_manage_visit_url(self):
        html = _render(
            allow_add_new_visit_date='1',
            type='by_class_section',
            class_section=self.record,
            record=self.record,
        )
        # 'class_visit:manage_visit' no longer exists — it is 'ce_manage_visit',
        # keyed on section_id.
        self.assertIn(f'/ce/class_visits/manage/{self.record.id}/', html)

    def test_add_button_hidden_when_not_allowed(self):
        html = _render(
            allow_add_new_visit_date='0',
            type='by_teacher',
            teacher=self.record,
            record=self.record,
        )
        self.assertNotIn('Add New Visit', html)

    def test_scopes_table_to_the_host_record(self):
        html = _render(
            allow_add_new_visit_date='1',
            type='by_class_section',
            class_section=self.record,
            record=self.record,
        )
        self.assertIn(f"d.class_section_id = '{self.record.id}'", html)

    def test_uses_current_serializer_url_fields(self):
        html = _render(
            allow_add_new_visit_date='1',
            type='by_class_section',
            class_section=self.record,
            record=self.record,
        )
        for field in ('ce_edit_url', 'ce_delete_url', 'ce_report_url', 'report_status'):
            self.assertIn(field, html)

    def test_no_stale_contract_references(self):
        html = _render(
            allow_add_new_visit_date='1',
            type='by_class_section',
            class_section=self.record,
            record=self.record,
        )
        stale = (
            'row.ce_url',
            'row.delete_url',
            'has_started_report',
            'has_submitted_report',
            '/ce/class_visits/visits/manage_visit_report/',
            '/faculty/class_visits/visits/edit_visit_report/',
            'data-data="createdon"',
        )
        for token in stale:
            self.assertNotIn(token, html, f'stale reference still in partial: {token}')


class EmbeddedVisitsFilterTest(TestCase):
    """The tabs scope the shared CE endpoint by section and academic year."""

    def setUp(self):
        self.factory = RequestFactory()
        self.staff = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x')

        self.ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        self.other_ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        self.term = Term.objects.create(
            academic_year=self.ay, code='FA', label=f'Fall-{_sfx()}')
        self.other_term = Term.objects.create(
            academic_year=self.other_ay, code='SP', label=f'Spring-{_sfx()}')

        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        course = Course.objects.create(
            catalog_number='101', title='A', cohort=cohort)
        teacher = Teacher.objects.create(user=User.objects.create_user(
            username=f't_{_sfx()}', email=f't_{_sfx()}@x.com', password='x'))

        self.section = ClassSection.objects.create(
            class_number='1001', term=self.term, course=course,
            teacher=teacher, status='A')
        self.other_section = ClassSection.objects.create(
            class_number='2001', term=self.other_term, course=course,
            teacher=teacher, status='A')

        self.visit = VisitSchedule.objects.create()
        self.visit.class_sections.add(self.section)
        self.other_visit = VisitSchedule.objects.create()
        self.other_visit.class_sections.add(self.other_section)

    def _ids(self, **params):
        request = self.factory.get('/ce/class_visits/api/visit_schedule/', params)
        request.user = self.staff
        viewset = CEVisitScheduleViewSet()
        viewset.request = request
        return set(viewset.get_queryset().values_list('id', flat=True))

    def test_unfiltered_returns_all(self):
        self.assertEqual(self._ids(), {self.visit.id, self.other_visit.id})

    def test_class_section_id_filter(self):
        self.assertEqual(
            self._ids(class_section_id=str(self.section.id)), {self.visit.id})

    def test_academic_year_id_filter(self):
        self.assertEqual(
            self._ids(academic_year_id=str(self.ay.id)), {self.visit.id})
