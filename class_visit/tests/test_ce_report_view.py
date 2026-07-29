"""CE visit report: iframe render + all-fields PDF download.

Mirrors the instructor page (see test_instructor_report_details) but CE sees
every report field regardless of its public flag, and can download a draft.
"""
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cis.models.course import Cohort, Course
from cis.models.section import ClassSection
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from class_visit.class_visit.models import VisitReport, VisitSchedule

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class CEViewReportTest(TestCase):
    def setUp(self):
        self._saved_receivers = list(user_logged_in.receivers)
        user_logged_in.receivers = []

        self.staff = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x',
            is_staff=True)
        self.staff.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.client.force_login(self.staff)

        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        course = Course.objects.create(
            catalog_number='101', title='Intro', cohort=cohort)
        teacher = Teacher.objects.create(user=User.objects.create_user(
            username=f't_{_sfx()}', email=f't_{_sfx()}@x.com', password='x',
            first_name='Ada', last_name='Nwosu'))
        self.section = ClassSection.objects.create(
            class_number='1001', section_number='02', term=term, course=course,
            teacher=teacher, status='A', period_time='3rd Period')

        self.visitor = User.objects.create_user(
            username=f'v_{_sfx()}', email=f'v_{_sfx()}@x.com', password='x',
            first_name='Dana', last_name='Reyes')

        self.visit = VisitSchedule.objects.create(
            visit_date=timezone.now(), type_of_visit='In-Person Observation')
        self.visit.class_sections.add(self.section)
        self.visit.visitors.add(self.visitor)

        self.url = reverse(
            'class_visit:ce_view_report', kwargs={'visit_id': self.visit.id})
        self.pdf_url = reverse(
            'class_visit:ce_report_pdf', kwargs={'visit_id': self.visit.id})

    def tearDown(self):
        user_logged_in.receivers = self._saved_receivers

    def _report(self, status='Submitted'):
        return VisitReport.objects.create(
            visit_schedule=self.visit, status=status,
            teacher_discussion='td', student_discussion='sd',
            visit_letter='letter', payment_processed='No')

    def test_ajax_render_is_a_styled_standalone_document(self):
        """The modal iframe needs its own <head> — cis/ajax-base.html has none,
        so the report used to render unstyled inside the frame."""
        resp = self.client.get(self.url + '?ajax=1')
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'class_visit/ce/view_report_ajax.html')
        html = resp.content.decode()
        self.assertIn('<!DOCTYPE html>', html)
        self.assertIn('bootstrap', html)
        self.assertNotIn('Back to Visits', html)
        self.assertIn('window.parent.closeVisitModal()', html)
        self.assertNotIn('X-Frame-Options', resp)

    def test_standalone_render_keeps_the_ce_chrome(self):
        resp = self.client.get(self.url)
        self.assertTemplateUsed(resp, 'class_visit/ce/view_report.html')
        self.assertIn('Back to Visits', resp.content.decode())

    def test_visit_details_rendered(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('In-Person Observation', html)
        self.assertIn('Reyes, Dana', html)
        self.assertIn('1001/02', html)
        self.assertIn('3rd Period', html)

    def test_no_pdf_link_without_a_report(self):
        self.assertNotIn('Download as PDF', self.client.get(self.url).content.decode())

    def test_pdf_link_shown_in_both_renders(self):
        self._report()
        for suffix in ('', '?ajax=1'):
            html = self.client.get(self.url + suffix).content.decode()
            self.assertIn('Download as PDF', html, suffix)
            self.assertIn(self.pdf_url, html, suffix)

    @patch('class_visit.class_visit.views.ce.pdf_service')
    def test_pdf_download_includes_all_fields(self, mock_pdf):
        """CE gets public_only=False — the instructor download is the public one."""
        mock_pdf.visit_letter_pdf.return_value = b'%PDF-1.4 fake'
        report = self._report()
        resp = self.client.get(self.pdf_url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        mock_pdf.visit_letter_pdf.assert_called_once_with(report, public_only=False)
        self.assertNotIn('/', resp['Content-Disposition'].split('filename=')[1])

    @patch('class_visit.class_visit.views.ce.pdf_service')
    def test_draft_report_is_downloadable(self, mock_pdf):
        mock_pdf.visit_letter_pdf.return_value = b'%PDF-1.4 fake'
        self._report(status='Draft')
        self.assertEqual(self.client.get(self.pdf_url).status_code, 200)

    def test_pdf_404s_without_a_report(self):
        self.assertEqual(self.client.get(self.pdf_url).status_code, 404)
