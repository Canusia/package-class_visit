"""Instructor sign-off, response and attachments (#14, supersedes #7).

An instructor could read a submitted report and download the PDF, but had no way to
record that they had seen it or to respond. Paper site-visit forms carry an instructor
signature line, so every tenant migrating off paper lost a step.

Advisory throughout: nothing here gates report submission, status, notifications or any
existing flow, and a report with no sign-off stays fully valid. The tests at the bottom
pin that.
"""
import datetime
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from cis.models.course import Cohort, Course
from cis.models.section import ClassSection
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from . import PKG
from ..models import VisitReport, VisitReportFile, VisitSchedule

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()

ON = {'is_active': 'No', 'instructor_signature': 'Yes'}
OFF = {'is_active': 'No', 'instructor_signature': 'No'}


def _sfx():
    return uuid.uuid4().hex[:8]


class InstructorSignoffTest(TestCase):
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

        cls.instructor_user = User.objects.create_user(
            username=f'ins_{_sfx()}', email=f'ins_{_sfx()}@x.com', password='x',
            first_name='Ida', last_name='Instructor')
        cls.instructor_user.groups.add(
            Group.objects.get_or_create(name='instructor')[0])
        cls.teacher = Teacher.objects.create(user=cls.instructor_user)

        other_user = User.objects.create_user(
            username=f'oth_{_sfx()}', email=f'oth_{_sfx()}@x.com', password='x')
        other_user.groups.add(Group.objects.get_or_create(name='instructor')[0])
        cls.other_instructor = other_user
        other_teacher = Teacher.objects.create(user=other_user)

        section = ClassSection.objects.create(
            course=course, term=term, teacher=cls.teacher,
            class_number=f'C-{_sfx()}', section_number='001')
        other_section = ClassSection.objects.create(
            course=course, term=term, teacher=other_teacher,
            class_number=f'C-{_sfx()}', section_number='002')

        cls.visitor = User.objects.create_user(
            username=f'fac_{_sfx()}', email=f'fac_{_sfx()}@x.com', password='x',
            first_name='Vera', last_name='Visitor')

        cls.visit = VisitSchedule.objects.create(
            visit_date=datetime.date(2026, 3, 1), type_of_visit='Initial', meta={})
        cls.visit.class_sections.add(section)
        cls.visit.visitors.add(cls.visitor)

        cls.other_visit = VisitSchedule.objects.create(
            visit_date=datetime.date(2026, 3, 1), type_of_visit='Initial', meta={})
        cls.other_visit.class_sections.add(other_section)

    def setUp(self):
        self.client = Client(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.instructor_user)
        self.report = VisitReport.objects.create(
            visit_schedule=self.visit, status='Submitted', meta={})

    def _settings(self, cfg):
        patcher = patch(f'{PKG}.settings.class_visit.class_visit.from_db',
                        return_value=cfg)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _sign_url(self, visit=None):
        return reverse('instructor_class_visit:sign_report',
                       kwargs={'visit_id': (visit or self.visit).id})

    def _detail_url(self, visit=None):
        return reverse('instructor_class_visit:report_detail',
                       kwargs={'visit_id': (visit or self.visit).id})

    # -- the setting gates the whole feature ---------------------------------

    def test_panel_absent_and_post_refused_when_setting_is_no(self):
        self._settings(OFF)

        self.assertNotIn('name="instructor_signature"',
                         self.client.get(self._detail_url()).content.decode())
        self.assertEqual(
            self.client.post(self._sign_url(), {'instructor_signature': 'Ida'}).status_code,
            404)
        self.report.refresh_from_db()
        self.assertEqual(self.report.instructor_signature, '')

    def test_panel_renders_when_setting_is_yes(self):
        self._settings(ON)
        html = self.client.get(self._detail_url()).content.decode()
        self.assertIn('name="instructor_signature"', html)
        self.assertIn('name="instructor_response"', html)

    # -- signing --------------------------------------------------------------

    def test_signing_records_name_and_timestamp(self):
        self._settings(ON)

        resp = self.client.post(self._sign_url(), {'instructor_signature': 'Ida Instructor'})

        self.assertEqual(resp.status_code, 302, getattr(resp, 'content', b'')[:200])
        self.report.refresh_from_db()
        self.assertEqual(self.report.instructor_signature, 'Ida Instructor')
        self.assertIsNotNone(self.report.instructor_signed_on)

    def test_signature_is_immutable_once_given(self):
        self._settings(ON)
        self.client.post(self._sign_url(), {'instructor_signature': 'First'})

        self.client.post(self._sign_url(), {'instructor_signature': 'Second'})

        self.report.refresh_from_db()
        self.assertEqual(self.report.instructor_signature, 'First')

    def test_draft_report_cannot_be_signed(self):
        self._settings(ON)
        VisitReport.objects.filter(pk=self.report.pk).update(status='Draft')

        resp = self.client.post(self._sign_url(), {'instructor_signature': 'Ida'})

        self.assertEqual(resp.status_code, 404)
        self.report.refresh_from_db()
        self.assertEqual(self.report.instructor_signature, '')

    def test_another_instructors_visit_is_refused(self):
        self._settings(ON)
        VisitReport.objects.create(
            visit_schedule=self.other_visit, status='Submitted', meta={})

        resp = self.client.post(self._sign_url(self.other_visit),
                                {'instructor_signature': 'Ida'})

        self.assertEqual(resp.status_code, 404)

    # -- response + attachment ------------------------------------------------

    def test_response_is_stored_with_a_timestamp(self):
        self._settings(ON)

        self.client.post(self._sign_url(), {
            'instructor_signature': 'Ida', 'instructor_response': 'I disagree about pacing.'})

        self.report.refresh_from_db()
        self.assertEqual(self.report.instructor_response, 'I disagree about pacing.')
        self.assertIsNotNone(self.report.instructor_responded_on)

    def test_response_file_is_stored_as_an_instructor_response(self):
        self._settings(ON)
        # VisitReportFile.file uses PrivateMediaStorage (S3); tests have no bucket.
        import tempfile

        from django.core.files.storage import FileSystemStorage

        field = VisitReportFile._meta.get_field('file')
        patcher = patch.object(field, 'storage',
                               FileSystemStorage(location=tempfile.mkdtemp()))
        patcher.start()
        self.addCleanup(patcher.stop)

        self.client.post(self._sign_url(), {
            'instructor_signature': 'Ida',
            'instructor_response': 'See attached.',
            'response_file': SimpleUploadedFile('reply.txt', b'my reply'),
        })

        attachment = VisitReportFile.objects.get(visit_report=self.report)
        self.assertEqual(attachment.kind, VisitReportFile.INSTRUCTOR_RESPONSE)
        self.assertEqual(attachment.uploaded_by_id, self.instructor_user.id)

    def test_a_response_may_be_added_without_signing(self):
        self._settings(ON)

        self.client.post(self._sign_url(), {'instructor_response': 'Comment only.'})

        self.report.refresh_from_db()
        self.assertEqual(self.report.instructor_response, 'Comment only.')
        self.assertEqual(self.report.instructor_signature, '')

    # -- re-submission invalidates the attestation ---------------------------

    def test_faculty_resubmission_clears_the_signature_but_keeps_the_response(self):
        self._settings(ON)
        self.client.post(self._sign_url(), {
            'instructor_signature': 'Ida', 'instructor_response': 'My words.'})

        self.report.refresh_from_db()
        self.report.clear_instructor_signature()

        self.report.refresh_from_db()
        self.assertEqual(self.report.instructor_signature, '')
        self.assertIsNone(self.report.instructor_signed_on)
        self.assertEqual(self.report.instructor_response, 'My words.')

    # -- the advisory guarantee ----------------------------------------------

    def test_sign_off_never_changes_report_status(self):
        self._settings(ON)
        self.client.post(self._sign_url(), {'instructor_signature': 'Ida'})

        self.report.refresh_from_db()
        self.assertEqual(self.report.status, 'Submitted')

    # -- the letter ----------------------------------------------------------

    def test_letter_shows_the_signature_and_response(self):
        from ..services.pdf import _build_letter_html

        self._settings(ON)
        self.client.post(self._sign_url(), {
            'instructor_signature': 'Ida Instructor',
            'instructor_response': 'I would add context about pacing.'})
        self.report.refresh_from_db()

        html = _build_letter_html(self.report)

        self.assertIn('Instructor Sign-Off', html)
        self.assertIn('Ida Instructor', html)
        self.assertIn('I would add context about pacing.', html)

    def test_letter_omits_the_block_entirely_when_unsigned(self):
        from ..services.pdf import _build_letter_html

        html = _build_letter_html(self.report)

        self.assertNotIn('Instructor Sign-Off', html)

    def test_public_only_letter_still_includes_the_response(self):
        from ..services.pdf import _build_letter_html

        self._settings(ON)
        self.client.post(self._sign_url(), {'instructor_response': 'My response.'})
        self.report.refresh_from_db()

        html = _build_letter_html(self.report, public_only=True)

        self.assertIn('My response.', html)
