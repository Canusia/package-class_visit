"""Save as Draft must not enforce required fields (#11).

`edit_visit_report` validated before it knew the intent: the form was built with every
definition's `required` flag applied, and `submit_action` was only read afterwards inside
`save()`. So on a tenant with required report fields, "Save as Draft" returned 400 with
field errors and saved nothing — the Draft → Submit workflow the module is built around
could not be used at all, and `required` could not be used for its obvious purpose.

Submitting still enforces every required field; that guarantee is what makes a Submitted
report meaningful.
"""
import json
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import Client, TestCase
from django.urls import reverse

from cis.models.course import Cohort, Course
from cis.models.section import ClassSection
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from . import PKG
from ..models import VisitReport, VisitSchedule

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()

FIELDS = [
    {'name': 'summary', 'label': 'Summary', 'type': 'textarea', 'required': True},
    {'name': 'rating', 'label': 'Rating', 'type': 'select', 'required': True,
     'options': ['Good', 'Needs work']},
    {'name': 'visited_on', 'label': 'Visited On', 'type': 'date', 'required': True},
    {'name': 'notes', 'label': 'Notes', 'type': 'text', 'required': False},
]

SETTINGS = {
    'report_fields_json': json.dumps(FIELDS),
    'visit_types': 'Initial|Follow-up',
}


def _sfx():
    return uuid.uuid4().hex[:8]


class DraftValidationTest(TestCase):
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
        term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        course = Course.objects.create(catalog_number='101', title='A', cohort=cohort)
        teacher = Teacher.objects.create(user=User.objects.create_user(
            username=f't_{_sfx()}', email=f't_{_sfx()}@x.com', password='x'))
        section = ClassSection.objects.create(
            course=course, term=term, teacher=teacher,
            class_number=f'C-{_sfx()}', section_number='001')

        cls.visitor = User.objects.create_user(
            username=f'fac_{_sfx()}', email=f'fac_{_sfx()}@x.com', password='x')
        cls.visitor.groups.add(Group.objects.get_or_create(name='faculty')[0])

        cls.visit = VisitSchedule.objects.create(
            visit_date='2026-03-01', type_of_visit='Initial', meta={})
        cls.visit.class_sections.add(section)
        cls.visit.visitors.add(cls.visitor)

    def setUp(self):
        self.client = Client(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.visitor)
        patcher = patch(f'{PKG}.services.report_fields._get_settings',
                        return_value=SETTINGS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _url(self):
        return reverse('faculty_class_visit:edit_visit_report',
                       kwargs={'visit_id': self.visit.id})

    def _post(self, action, **data):
        payload = {'submit_action': action}
        payload.update(data)
        return self.client.post(self._url(), payload)

    # -- draft ---------------------------------------------------------------

    def test_draft_saves_with_every_required_field_blank(self):
        resp = self._post('draft', summary='', rating='', visited_on='', notes='')

        self.assertEqual(resp.status_code, 200, resp.content[:300])
        body = json.loads(resp.content)
        self.assertTrue(body['success'])
        self.assertEqual(body['status'], 'draft')
        report = VisitReport.objects.get(visit_schedule=self.visit)
        self.assertEqual(report.status, 'Draft')

    def test_draft_accepts_a_blank_required_select(self):
        """The regression a naive fix reintroduces: a required ChoiceField has no
        blank choice, so relaxing `required` alone still fails with 'not a valid
        choice'."""
        resp = self._post('draft', summary='partial', rating='', visited_on='')

        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self.assertTrue(json.loads(resp.content)['success'])

    def test_draft_keeps_the_values_that_were_filled_in(self):
        self._post('draft', summary='halfway', rating='Good', visited_on='')

        report = VisitReport.objects.get(visit_schedule=self.visit)
        self.assertEqual(report.meta['summary'], 'halfway')
        self.assertEqual(report.meta['rating'], 'Good')

    def test_draft_with_a_blank_date_does_not_break_meta_coercion(self):
        resp = self._post('draft', summary='x', rating='', visited_on='')
        self.assertEqual(resp.status_code, 200, resp.content[:300])

    # -- submit --------------------------------------------------------------

    def test_submit_still_rejects_blank_required_fields(self):
        resp = self._post('submit', summary='', rating='', visited_on='', notes='')

        self.assertEqual(resp.status_code, 400)
        errors = json.loads(json.loads(resp.content)['errors'])
        for name in ('summary', 'rating', 'visited_on'):
            self.assertIn(name, errors)
        self.assertFalse(VisitReport.objects.filter(visit_schedule=self.visit).exists())

    def test_submit_succeeds_when_complete(self):
        resp = self._post('submit', summary='done', rating='Good',
                          visited_on='2026-03-02', notes='')

        self.assertEqual(resp.status_code, 200, resp.content[:300])
        report = VisitReport.objects.get(visit_schedule=self.visit)
        self.assertEqual(report.status, 'Submitted')

    def test_draft_then_submit(self):
        self._post('draft', summary='halfway', rating='', visited_on='')
        resp = self._post('submit', summary='halfway', rating='Needs work',
                          visited_on='2026-03-02')

        self.assertEqual(resp.status_code, 200, resp.content[:300])
        report = VisitReport.objects.get(visit_schedule=self.visit)
        self.assertEqual(report.status, 'Submitted')
        self.assertEqual(report.meta['summary'], 'halfway')

    # -- the form still communicates intent ----------------------------------

    def test_get_renders_required_fields_as_required(self):
        html = self.client.get(self._url()).content.decode()
        self.assertIn('name="summary"', html)
        self.assertIn('required', html)
