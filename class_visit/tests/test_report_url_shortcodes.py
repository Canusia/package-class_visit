"""{{public_report_url}} and {{report_url}} must render real links (#4).

All three sends passed the shortcode in as a literal empty string, with TODO comments
confirming it was left unfinished. `render_template` is plain Django Template/Context, so
an empty value renders as nothing at all -- no error, no literal {{...}}, no log line. The
shortcodes are advertised in three settings help_texts, the README and the workbook, so
tenants wrote "click the link below" around links that never appeared.

Both links require login: they point at the existing per-portal pages, and a recipient who
is not signed in lands on the login page and arrives after signing in. No tokenized public
report view, no new unauthenticated surface.
"""
import datetime
import uuid
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cis.models.course import Cohort, Course
from cis.models.section import ClassSection
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from . import PKG
from ..models import VisitReport, VisitSchedule
from ..services import emails as email_service

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class ReportUrlShortcodeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        course = Course.objects.create(catalog_number='101', title='A', cohort=cohort)
        cls.teacher = Teacher.objects.create(user=User.objects.create_user(
            username=f't_{_sfx()}', email=f't_{_sfx()}@x.com', password='x',
            first_name='Tess', last_name='Teacher'))
        section = ClassSection.objects.create(
            course=course, term=term, teacher=cls.teacher,
            class_number=f'C-{_sfx()}', section_number='001')

        cls.visitor = User.objects.create_user(
            username=f'fac_{_sfx()}', email=f'fac_{_sfx()}@x.com', password='x',
            first_name='Vera', last_name='Visitor')

        cls.visit = VisitSchedule.objects.create(
            visit_date=datetime.date(2026, 3, 1), type_of_visit='Initial', meta={})
        cls.visit.class_sections.add(section)
        cls.visit.visitors.add(cls.visitor)
        cls.report = VisitReport.objects.create(
            visit_schedule=cls.visit, status='Submitted', meta={})

    def setUp(self):
        site = MagicMock()
        site.domain = 'ce.example.edu'
        patcher = patch(f'{PKG}.services.emails.Site')
        self.mock_site = patcher.start()
        self.mock_site.objects.get_current.return_value = site
        self.addCleanup(patcher.stop)

    def _sent_body(self, cfg, send):
        with patch(f'{PKG}.services.emails._get_settings', return_value=cfg), \
             patch(f'{PKG}.services.emails.send_app_email') as mock_send:
            send()
        self.assertTrue(mock_send.called, 'no email was sent')
        return mock_send.call_args.args[1]

    # -- the three sends -----------------------------------------------------

    def test_teacher_submit_email_renders_the_instructor_report_url(self):
        body = self._sent_body(
            {'is_active': 'Yes', 'notify_teacher_on_submit': 'Yes',
             'teacher_submit_subject': 's',
             'teacher_submit_message': 'Link: {{public_report_url}}'},
            lambda: email_service.notify_teacher_report_submitted(self.report))

        expected = reverse('instructor_class_visit:report_detail',
                           kwargs={'visit_id': self.visit.id})
        self.assertIn(f'https://ce.example.edu{expected}', body)

    def test_visitor_reminder_renders_the_faculty_report_url(self):
        body = self._sent_body(
            {'is_active': 'Yes', 'visitor_reminder_subject': 's',
             'visitor_reminder_message': 'Link: {{report_url}}'},
            lambda: email_service.remind_visitor_report_pending(self.visit))

        expected = reverse('faculty_class_visit:edit_visit_report',
                           kwargs={'visit_id': self.visit.id})
        self.assertIn(f'https://ce.example.edu{expected}', body)

    def test_payment_processed_renders_the_faculty_report_url(self):
        body = self._sent_body(
            {'is_active': 'Yes', 'payment_tracking': 'Yes',
             'notify_visitor_on_paid': 'Yes', 'visitor_paid_subject': 's',
             'visitor_paid_message': 'Link: {{report_url}}'},
            lambda: email_service.notify_visitor_payment_processed(self.report))

        expected = reverse('faculty_class_visit:edit_visit_report',
                           kwargs={'visit_id': self.visit.id})
        self.assertIn(f'https://ce.example.edu{expected}', body)

    def test_office_email_renders_the_instructor_report_url(self):
        """notify_notification_target reuses teacher_submit_message but built a
        context without public_report_url at all, so the office copy dropped the
        link too."""
        body = self._sent_body(
            {'is_active': 'Yes', 'notify_target': 'generic_email',
             'generic_email': 'office@example.edu',
             'teacher_submit_subject': 's',
             'teacher_submit_message': 'Link: {{public_report_url}}'},
            lambda: email_service.notify_notification_target(self.report))

        self.assertIn('https://ce.example.edu', body)

    # -- the regression guard ------------------------------------------------

    def test_no_send_renders_an_empty_shortcode(self):
        for cfg, send, code in (
            ({'is_active': 'Yes', 'notify_teacher_on_submit': 'Yes',
              'teacher_submit_subject': 's',
              'teacher_submit_message': 'X{{public_report_url}}Y'},
             lambda: email_service.notify_teacher_report_submitted(self.report),
             'public_report_url'),
            ({'is_active': 'Yes', 'visitor_reminder_subject': 's',
              'visitor_reminder_message': 'X{{report_url}}Y'},
             lambda: email_service.remind_visitor_report_pending(self.visit),
             'report_url'),
        ):
            with self.subTest(code=code):
                self.assertNotIn('XY', self._sent_body(cfg, send))
