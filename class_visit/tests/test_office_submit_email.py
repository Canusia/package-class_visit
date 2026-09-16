"""The office "report submitted" email gets its own wording and an off switch (#5).

It had no subject or body of its own: notify_notification_target rendered
`teacher_submit_subject` / `teacher_submit_message` verbatim, so course administrators
received copy addressed to the instructor who was observed ("Thank you for participating
in your site visit..."). It also fired unconditionally, unlike every other notification
in the module.

Upgrade compatibility is the constraint that shapes the fix: the default is Yes with the
office body falling back to the instructor body, so a tenant that upgrades and configures
nothing keeps sending exactly the email it sends today.
"""
import datetime
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from cis.models.course import Cohort, Course, CourseAdministrator
from cis.models.section import ClassSection
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from . import PKG
from ..models import VisitReport, VisitSchedule
from ..services import emails as email_service

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


BASE_CFG = {
    'is_active': 'Yes',
    'notify_target': 'generic_email',
    'generic_email': 'office@example.edu',
    'teacher_submit_subject': 'Instructor subject',
    'teacher_submit_message': 'Dear {{teacher_first_name}}, your visit is complete.',
}


class OfficeSubmitEmailTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        cls.course = Course.objects.create(
            catalog_number='101', title='A', cohort=cohort)
        teacher = Teacher.objects.create(user=User.objects.create_user(
            username=f't_{_sfx()}', email=f't_{_sfx()}@x.com', password='x',
            first_name='Tess', last_name='Teacher'))
        section = ClassSection.objects.create(
            course=cls.course, term=term, teacher=teacher,
            class_number=f'C-{_sfx()}', section_number='001')

        cls.visit = VisitSchedule.objects.create(
            visit_date=datetime.date(2026, 3, 1), type_of_visit='Initial', meta={})
        cls.visit.class_sections.add(section)
        cls.report = VisitReport.objects.create(
            visit_schedule=cls.visit, status='Submitted', meta={})

    def _send(self, **overrides):
        cfg = dict(BASE_CFG)
        cfg.update(overrides)
        with patch(f'{PKG}.services.emails._get_settings', return_value=cfg), \
             patch(f'{PKG}.services.emails.send_app_email') as mock_send:
            email_service.notify_notification_target(self.report)
        return mock_send

    # -- the switch ----------------------------------------------------------

    def test_disabled_sends_nothing(self):
        mock_send = self._send(notify_office_on_submit='No')

        mock_send.assert_not_called()
        self.report.refresh_from_db()
        self.assertNotIn('course_admin_email_sent_on', self.report.meta)

    def test_enabled_by_default_for_upgrade_compatibility(self):
        """No key configured at all: the tenant keeps sending what it sends today."""
        mock_send = self._send()

        self.assertTrue(mock_send.called)

    # -- its own wording -----------------------------------------------------

    def test_office_subject_and_body_are_used_when_set(self):
        mock_send = self._send(
            notify_office_on_submit='Yes',
            office_submit_subject='Office subject',
            office_submit_message='A report was submitted for {{class_sections}}.')

        subject, body, recipients = mock_send.call_args.args[:3]
        self.assertEqual(subject, 'Office subject')
        self.assertIn('A report was submitted', body)
        self.assertNotIn('Dear Tess', body)
        self.assertEqual(recipients, ['office@example.edu'])

    def test_falls_back_to_the_instructor_copy_when_office_body_is_blank(self):
        mock_send = self._send(
            notify_office_on_submit='Yes',
            office_submit_subject='', office_submit_message='')

        subject, body = mock_send.call_args.args[:2]
        self.assertEqual(subject, 'Instructor subject')
        self.assertIn('Dear Tess', body)

    def test_office_body_renders_both_shortcodes(self):
        mock_send = self._send(
            notify_office_on_submit='Yes',
            office_submit_subject='s',
            office_submit_message='{{class_sections}} | {{public_report_url}}')

        body = mock_send.call_args.args[1]
        self.assertIn('https://', body)
        self.assertNotIn('|  ', body.replace('| ', '|X ', 1))  # link is not blank

    # -- recipients are unchanged -------------------------------------------

    def test_course_administrator_target_still_resolves_administrators(self):
        admin = User.objects.create_user(
            username=f'adm_{_sfx()}', email=f'adm_{_sfx()}@x.com', password='x')
        CourseAdministrator.objects.create(
            user=admin, course=self.course, role='Administrator', status='Active')

        mock_send = self._send(
            notify_office_on_submit='Yes', notify_target='course_administrator')

        self.assertEqual(mock_send.call_args.args[2], [admin.email])

    def test_blank_generic_email_sends_nothing(self):
        mock_send = self._send(notify_office_on_submit='Yes', generic_email='')

        mock_send.assert_not_called()

    def test_successful_send_still_stamps_meta(self):
        self._send(notify_office_on_submit='Yes')

        self.report.refresh_from_db()
        self.assertIn('course_admin_email_sent_on', self.report.meta)

    def test_stamping_does_not_clobber_other_meta_keys(self):
        VisitReport.objects.filter(pk=self.report.pk).update(
            meta={'visit_letter_sent_on': '01/01/2026'})
        self.report.refresh_from_db()

        self._send(notify_office_on_submit='Yes')

        self.report.refresh_from_db()
        self.assertEqual(self.report.meta['visit_letter_sent_on'], '01/01/2026')
        self.assertIn('course_admin_email_sent_on', self.report.meta)


class InstallDefaultsTest(TestCase):
    def test_new_keys_are_seeded(self):
        from django.http import HttpRequest

        from cis.models.settings import Setting

        from ..settings.class_visit import class_visit as CVSettings

        Setting.objects.filter(key=CVSettings.key).delete()
        CVSettings(HttpRequest()).install()

        value = Setting.objects.get(key=CVSettings.key).value
        self.assertEqual(value['notify_office_on_submit'], 'Yes')
        self.assertIn('office_submit_subject', value)
        self.assertIn('office_submit_message', value)
