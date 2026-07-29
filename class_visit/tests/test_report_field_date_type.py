"""A `date` report field must survive the round-trip through meta.

`forms.DateField` cleans to a `datetime.date`, and VisitReport.meta is a
JSONField using the stock encoder — assigning the date straight in made
report.save() raise "Object of type date is not JSON serializable", so
configuring any date field in Report Fields (JSON) 500'd the report form.

Values are stored ISO (YYYY-MM-DD), which is also what `<input type="date">`
needs back as its initial value.
"""
import datetime
import json
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from cis.models.course import Cohort, Course
from cis.models.section import ClassSection
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from class_visit.class_visit.models import VisitReport, VisitSchedule
from class_visit.class_visit.services import report_fields as rf

User = get_user_model()

FIELD_DEFS = [
    {'name': 'follow_up_on', 'label': 'Follow Up On', 'type': 'date',
     'public': True, 'required': False},
    {'name': 'notes', 'label': 'Notes', 'type': 'text',
     'public': True, 'required': False},
]


def _sfx():
    return uuid.uuid4().hex[:8]


class MetaValueCoercionTest(SimpleTestCase):
    def test_date_is_coerced_to_iso(self):
        self.assertEqual(
            rf.coerce_meta_value(datetime.date(2026, 7, 23)), '2026-07-23')

    def test_datetime_is_coerced_to_iso(self):
        value = rf.coerce_meta_value(datetime.datetime(2026, 7, 23, 14, 30))
        self.assertTrue(value.startswith('2026-07-23'))

    def test_json_native_values_pass_through(self):
        for value in ('text', 7, 1.5, True, False, None, ['a'], {'k': 'v'}):
            self.assertEqual(rf.coerce_meta_value(value), value)

    def test_coerced_values_are_json_serializable(self):
        json.dumps({'d': rf.coerce_meta_value(datetime.date(2026, 7, 23))})


class DateReportFieldSaveTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username=f'fac_{_sfx()}', email=f'fac_{_sfx()}@x.com', password='x')

        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        course = Course.objects.create(
            catalog_number='101', title='Intro', cohort=cohort)
        teacher = Teacher.objects.create(user=User.objects.create_user(
            username=f't_{_sfx()}', email=f't_{_sfx()}@x.com', password='x'))
        self.section = ClassSection.objects.create(
            class_number='1001', term=term, course=course, teacher=teacher,
            status='A')

        self.visit = VisitSchedule.objects.create(
            visit_date=timezone.now(), type_of_visit='Observation')
        self.visit.class_sections.add(self.section)

    def _patched_settings(self):
        return patch.object(
            rf, '_get_settings',
            return_value={'report_fields_json': json.dumps(FIELD_DEFS)})

    def test_form_with_a_date_field_saves(self):
        from class_visit.class_visit.forms.faculty import VisitReportDynamicForm

        with self._patched_settings():
            form = VisitReportDynamicForm(
                visit=self.visit,
                data={'follow_up_on': '2026-07-23', 'notes': 'ok',
                      'submit_action': 'draft'},
            )
            self.assertTrue(form.is_valid(), form.errors)
            report = form.save(created_by_user=self.user)

        report.refresh_from_db()
        self.assertEqual(report.meta['follow_up_on'], '2026-07-23')
        self.assertEqual(report.meta['notes'], 'ok')

    def test_stored_iso_value_repopulates_the_date_input(self):
        """<input type="date"> only accepts YYYY-MM-DD as its value."""
        with self._patched_settings():
            fields = rf.build_report_form_fields(
                initial={'follow_up_on': '2026-07-23'})
        self.assertEqual(fields['follow_up_on'].initial, '2026-07-23')

    def test_date_value_displays_in_project_date_format(self):
        report = VisitReport.objects.create(
            visit_schedule=self.visit, status='Submitted',
            teacher_discussion='', student_discussion='', visit_letter='',
            payment_processed='No', meta={'follow_up_on': '2026-07-23',
                                          'notes': 'ok'})
        with self._patched_settings():
            rows = rf.report_values_for_display(report)
        by_label = {r['label']: r['value'] for r in rows}
        self.assertEqual(by_label['Follow Up On'], '07/23/2026')
        self.assertEqual(by_label['Notes'], 'ok')
