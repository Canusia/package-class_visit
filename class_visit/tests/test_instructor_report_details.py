"""The instructor report page shows who visited and what was visited.

Previously it rendered only the public report fields, so an instructor could
read the write-up without seeing the visitor, the type of visit, or which
section it covered — all of which the PDF letter
(`class_visit/letter_body.html`) has always carried.

The details block mirrors that letter header and adds the visitor name(s).
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
from . import PKG

from ..models import VisitReport, VisitSchedule

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class InstructorReportDetailsTest(TestCase):
    def setUp(self):
        self._saved_receivers = list(user_logged_in.receivers)
        user_logged_in.receivers = []

        self.user = User.objects.create_user(
            username=f'inst_{_sfx()}', email=f'inst_{_sfx()}@x.com', password='x',
            first_name='Sam', last_name='Okafor')
        self.user.groups.add(Group.objects.get_or_create(name='instructor')[0])
        self.teacher = Teacher.objects.create(user=self.user)
        self.client.force_login(self.user)

        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.course = Course.objects.create(
            catalog_number='101', title='Intro to Testing', cohort=cohort)
        self.section = ClassSection.objects.create(
            class_number='1001', section_number='02', term=term,
            course=self.course, teacher=self.teacher, status='A',
            period_time='2nd Period')

        self.visitor = User.objects.create_user(
            username=f'vis_{_sfx()}', email=f'vis_{_sfx()}@x.com', password='x',
            first_name='Dana', last_name='Reyes')

        self.visit = VisitSchedule.objects.create(
            visit_date=timezone.now(), type_of_visit='In-Person Observation')
        self.visit.class_sections.add(self.section)
        self.visit.visitors.add(self.visitor)

        self.url = reverse(
            'instructor_class_visit:report_detail',
            kwargs={'visit_id': self.visit.id})

    def tearDown(self):
        user_logged_in.receivers = self._saved_receivers

    def test_shows_visitor_name(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('Visitor(s)', html)
        self.assertIn('Reyes, Dana', html)

    def test_shows_class_details(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('Class Section(s)', html)
        self.assertIn('1001/02', html)
        self.assertIn('2nd Period', html)
        self.assertIn(str(self.course), html)

    def test_shows_instructor_type_and_date(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('In-Person Observation', html)
        self.assertIn(self.visit.visit_date_sexy, html)
        self.assertIn('Sam Okafor', html)

    def test_details_shown_even_without_a_submitted_report(self):
        """The visit facts are known before the write-up lands."""
        html = self.client.get(self.url).content.decode()
        self.assertIn('The visit report is not available yet', html)
        self.assertIn('Reyes, Dana', html)

    def test_details_match_the_pdf_letter_header(self):
        """Same labels the PDF letter carries, so the two don't drift."""
        html = self.client.get(self.url).content.decode()
        for label in ('Instructor', 'Visit Date', 'Type of Visit', 'Class Section(s)'):
            self.assertIn(label, html)

    def test_ajax_render_is_standalone_and_frameable(self):
        """?ajax=1 is what the visits-page modal loads in its iframe."""
        resp = self.client.get(self.url + '?ajax=1')
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(
            resp, 'class_visit/instructor/report_detail_ajax.html')
        html = resp.content.decode()
        # own document, not the portal chrome
        self.assertIn('<!DOCTYPE html>', html)
        self.assertNotIn('Back to My Visits', html)
        self.assertIn('window.parent.closeReportModal()', html)
        # X_FRAME_OPTIONS defaults to DENY, so the view must be exempt
        self.assertNotIn('X-Frame-Options', resp)

    def test_standalone_render_keeps_the_portal_chrome(self):
        resp = self.client.get(self.url)
        self.assertTemplateUsed(resp, 'class_visit/instructor/report_detail.html')
        self.assertIn('Back to My Visits', resp.content.decode())

    def test_index_wires_the_report_modal(self):
        html = self.client.get(reverse('instructor_class_visit:index')).content.decode()
        self.assertIn('id="report_modal"', html)
        self.assertIn('id="report_modal_src"', html)

    def _submit_report(self):
        return VisitReport.objects.create(
            visit_schedule=self.visit, status='Submitted',
            teacher_discussion='td', student_discussion='sd',
            visit_letter='letter', payment_processed='No')

    def test_no_pdf_link_until_the_report_is_submitted(self):
        html = self.client.get(self.url).content.decode()
        self.assertNotIn('Download as PDF', html)

    def test_pdf_link_shown_once_submitted(self):
        self._submit_report()
        pdf_url = reverse(
            'instructor_class_visit:report_pdf', kwargs={'visit_id': self.visit.id})
        for suffix in ('', '?ajax=1'):
            html = self.client.get(self.url + suffix).content.decode()
            self.assertIn('Download as PDF', html, suffix)
            self.assertIn(pdf_url, html, suffix)

    def test_pdf_link_shown_when_no_field_is_public(self):
        """Downloadability follows the report's status, not whether any of its
        fields happen to be flagged public."""
        self._submit_report()
        resp = self.client.get(self.url)
        self.assertFalse(resp.context['public_values'])
        self.assertTrue(resp.context['can_download'])
        self.assertIn('Download as PDF', resp.content.decode())

    @patch(f'{PKG}.views.instructor.visit_letter_pdf')
    def test_pdf_download_returns_public_only_letter(self, mock_pdf):
        mock_pdf.return_value = b'%PDF-1.4 fake'
        report = self._submit_report()
        resp = self.client.get(reverse(
            'instructor_class_visit:report_pdf', kwargs={'visit_id': self.visit.id}))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertIn('attachment;', resp['Content-Disposition'])
        # m/d/Y slashes are not filename-safe
        self.assertNotIn('/', resp['Content-Disposition'].split('filename=')[1])
        mock_pdf.assert_called_once_with(report, public_only=True)

    def test_pdf_download_404s_for_an_unsubmitted_report(self):
        resp = self.client.get(reverse(
            'instructor_class_visit:report_pdf', kwargs={'visit_id': self.visit.id}))
        self.assertEqual(resp.status_code, 404)

    @patch(f'{PKG}.views.instructor.visit_letter_pdf')
    def test_pdf_download_404s_for_another_instructors_visit(self, mock_pdf):
        mock_pdf.return_value = b'%PDF-1.4 fake'
        self._submit_report()
        other = User.objects.create_user(
            username=f'oth_{_sfx()}', email=f'oth_{_sfx()}@x.com', password='x')
        other.groups.add(Group.objects.get(name='instructor'))
        Teacher.objects.create(user=other)
        self.client.force_login(other)
        resp = self.client.get(reverse(
            'instructor_class_visit:report_pdf', kwargs={'visit_id': self.visit.id}))
        self.assertEqual(resp.status_code, 404)
        mock_pdf.assert_not_called()

    def test_another_instructors_visit_is_not_readable(self):
        other = User.objects.create_user(
            username=f'oth_{_sfx()}', email=f'oth_{_sfx()}@x.com', password='x')
        other.groups.add(Group.objects.get(name='instructor'))
        Teacher.objects.create(user=other)
        self.client.force_login(other)
        self.assertEqual(self.client.get(self.url).status_code, 404)
