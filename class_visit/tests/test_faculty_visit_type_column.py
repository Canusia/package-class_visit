"""Both faculty visit tables surface the visit type.

`#all` (Scheduled Observations) gets it as its own sortable column; the
`#schedule_visit` tab shows it next to each existing visit's date in the
section's Visit(s) cell.

The `#all` column is server-side ordered/searched off the real
`type_of_visit` CharField, so the `<th>` must carry it as
`data-data`/`data-name` and the serializer must always emit it
(rest_framework_datatables drops fields that are neither requested by a
column nor in `datatables_always_serialize`).
"""
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from cis.models.course import Cohort, Course, CourseAdministrator
from cis.models.section import ClassSection
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from class_visit.class_visit.models import VisitSchedule
from class_visit.class_visit.serializers.faculty import (
    FacultyVisitScheduleSerializer,
    _MinimalVisitScheduleSerializer,
)

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class FacultyVisitTypeSerializedTest(SimpleTestCase):
    def test_type_of_visit_always_serialized(self):
        always = FacultyVisitScheduleSerializer.Meta.datatables_always_serialize
        self.assertIn('type_of_visit', always)

    def test_nested_visit_serializer_carries_type(self):
        """The #schedule_visit tab renders visits from this nested serializer —
        its explicit `fields` list drops anything not named."""
        declared = set(_MinimalVisitScheduleSerializer().fields.keys())
        self.assertIn('type_of_visit', declared)
        self.assertIn(
            'type_of_visit',
            _MinimalVisitScheduleSerializer.Meta.datatables_always_serialize)


class FacultyVisitTypeColumnTest(TestCase):
    """The visits page renders a Type column wired to type_of_visit."""

    def setUp(self):
        self._saved_receivers = list(user_logged_in.receivers)
        user_logged_in.receivers = []

        self.faculty = User.objects.create_user(
            username=f'fac_{_sfx()}', email=f'fac_{_sfx()}@x.com', password='x')
        self.faculty.groups.add(Group.objects.get_or_create(name='faculty')[0])
        self.client.force_login(self.faculty)

        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        course = Course.objects.create(catalog_number='101', title='A', cohort=cohort)
        teacher = Teacher.objects.create(user=User.objects.create_user(
            username=f't_{_sfx()}', email=f't_{_sfx()}@x.com', password='x'))
        self.section = ClassSection.objects.create(
            class_number='1001', term=term, course=course, teacher=teacher, status='A')
        CourseAdministrator.objects.create(
            user=self.faculty, course=course, role='Faculty', status='Active')

        self.visit = VisitSchedule.objects.create(type_of_visit='Virtual Observation')
        self.visit.class_sections.add(self.section)

    def tearDown(self):
        user_logged_in.receivers = self._saved_receivers

    def test_header_declares_type_of_visit(self):
        resp = self.client.get(reverse('faculty_class_visit:visits'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn(
            '<th data-data="type_of_visit" data-name="type_of_visit">Type</th>', html)

    def test_datatable_renders_the_type_cell(self):
        resp = self.client.get(reverse('faculty_class_visit:visits'))
        self.assertIn('row.type_of_visit', resp.content.decode())

    def test_type_sits_between_visit_date_and_scheduled_on(self):
        """Column defs are positional — Type must land in the same slot as its
        header, or every cell after it shifts."""
        import re
        html = self.client.get(
            reverse('faculty_class_visit:visits')).content.decode()
        thead = re.search(
            r'id="records_all".*?<thead>(.*?)</thead>', html, re.S).group(1)
        names = re.findall(r'<th[^>]*data-name="([^"]+)"', thead)
        self.assertEqual(
            names[:5],
            ['visit_date', 'type_of_visit', 'createdon', 'class_sections', 'visitors'],
        )
        # visit_date is still column index 1 (index 0 is the select-all checkbox),
        # which the table's default ordering depends on.
        self.assertIn('order: [[1, \'desc\']]', html)

    def test_nested_and_computed_columns_are_not_searchable(self):
        """No filterable model field behind them — a global search over these
        columns 500s the endpoint with a FieldError."""
        import re
        html = self.client.get(
            reverse('faculty_class_visit:visits')).content.decode()
        thead = re.search(
            r'id="records_all".*?<thead>(.*?)</thead>', html, re.S).group(1)
        for th in re.findall(r'<th[^>]*>', thead):
            name = re.search(r'data-name="([^"]+)"', th)
            if name and name.group(1) in (
                    'class_sections', 'visitors', 'report_status',
                    'payment_status', 'id'):
                self.assertIn('searchable="0"', th, f'searchable column: {th}')

    def test_schedule_visit_tab_shows_type_with_the_date(self):
        """Each existing visit in a section's Visit(s) cell shows its type."""
        html = self.client.get(
            reverse('faculty_class_visit:visits')).content.decode()
        cell = html.split('$.each(row.visit_schedule')[1].split('schedule_visit_url')[0]
        self.assertIn('v.visit_date', cell)
        self.assertIn('v.type_of_visit', cell)

    def test_type_is_html_escaped_in_both_renderers(self):
        """type_of_visit is free text concatenated into a DataTables renderer's
        HTML string — it must go through esc()."""
        html = self.client.get(
            reverse('faculty_class_visit:visits')).content.decode()
        self.assertIn('function esc(s)', html)
        self.assertIn('esc(v.type_of_visit)', html)
        self.assertIn('esc(row.type_of_visit)', html)

    def test_nested_serializer_emits_the_type(self):
        data = _MinimalVisitScheduleSerializer(self.visit).data
        self.assertEqual(data['type_of_visit'], 'Virtual Observation')

    @patch('class_visit.class_visit.views.faculty.ClassVisitSettings')
    def test_schedule_visit_api_nests_the_type(self, MockSettings):
        MockSettings.from_db.return_value = {'section_status_filter': 'active'}
        resp = self.client.get(
            '/faculty/class_visits/api/class_sections/?format=datatables')
        self.assertEqual(resp.status_code, 200)
        rows = [r for r in resp.json()['data'] if r['id'] == str(self.section.id)]
        self.assertEqual(len(rows), 1, 'the overseen section should be listed')
        self.assertEqual(
            [(v['visit_date'], v['type_of_visit']) for v in rows[0]['visit_schedule']],
            [(None, 'Virtual Observation')],
        )

    def test_api_returns_the_visit_type(self):
        resp = self.client.get(
            '/faculty/class_visits/api/visit_schedule/?format=datatables')
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()['data']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['type_of_visit'], 'Virtual Observation')
