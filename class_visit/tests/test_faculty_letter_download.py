"""Faculty letter downloads: bulk export and per-row (#13).

Two gaps combined into "faculty have no working way to download a letter":

1. The visits DataTable posts **VisitSchedule** ids (visits.html:202), while
   do_bulk_action filtered **VisitReport** primary keys with them. Disjoint UUID sets,
   so the queryset was always empty and every selection returned "No reports found."
   CE gets this right by mapping schedule -> visit.report.
2. There was no per-row download at all, so there was no fallback path.

Real rows throughout, deliberately. tests/test_views_faculty.py's BulkPdfActionTest
patches VisitReport and stubs objects.filter().distinct(), which is exactly why an
id-type mismatch could ship with a passing test.
"""
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import Client, TestCase
from django.urls import reverse

from cis.models.course import Cohort, Course, CourseAdministrator
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


def _sfx():
    return uuid.uuid4().hex[:8]


class FacultyLetterDownloadTest(TestCase):
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
        cls.term = Term.objects.create(
            academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        cls.mine = Course.objects.create(
            catalog_number='101', title='Mine', cohort=cohort)
        cls.theirs = Course.objects.create(
            catalog_number='102', title='Theirs', cohort=cohort)

        cls.faculty = User.objects.create_user(
            username=f'fac_{_sfx()}', email=f'fac_{_sfx()}@x.com', password='x')
        cls.faculty.groups.add(Group.objects.get_or_create(name='faculty')[0])
        CourseAdministrator.objects.create(
            user=cls.faculty, course=cls.mine, role='Faculty', status='Active')

        cls.visit_with_report = cls._visit(cls.mine)
        cls.report = VisitReport.objects.create(
            visit_schedule=cls.visit_with_report, status='Submitted', meta={})

        cls.visit_without_report = cls._visit(cls.mine)

        cls.foreign_visit = cls._visit(cls.theirs)
        cls.foreign_report = VisitReport.objects.create(
            visit_schedule=cls.foreign_visit, status='Submitted', meta={})

    @classmethod
    def _visit(cls, course):
        teacher = Teacher.objects.create(user=User.objects.create_user(
            username=f't_{_sfx()}', email=f't_{_sfx()}@x.com', password='x'))
        section = ClassSection.objects.create(
            course=course, term=cls.term, teacher=teacher,
            class_number=f'C-{_sfx()}', section_number='001')
        visit = VisitSchedule.objects.create(
            visit_date='2026-03-01', type_of_visit='Initial', meta={})
        visit.class_sections.add(section)
        visit.visitors.add(cls.faculty)
        return visit

    def setUp(self):
        self.client = Client(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.faculty)

    def _bulk(self, *visits, public_only='0'):
        return self.client.post(
            reverse('faculty_class_visit:bulk_action'),
            {'action': 'export_pdf', 'public_only': public_only,
             'ids[]': [str(v.id) for v in visits]})

    # -- bulk export ---------------------------------------------------------

    def test_bulk_export_accepts_the_schedule_ids_the_page_posts(self):
        with patch(f'{PKG}.views.faculty.pdf_service.visit_letters_pdf',
                   return_value=b'%PDF-1.4') as mock_pdf:
            resp = self._bulk(self.visit_with_report)

        self.assertEqual(resp.status_code, 200, resp.content[:200])
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        reports, = mock_pdf.call_args.args
        self.assertEqual([r.pk for r in reports], [self.report.pk])

    def test_bulk_export_excludes_a_visit_outside_the_faculty_scope(self):
        with patch(f'{PKG}.views.faculty.pdf_service.visit_letters_pdf',
                   return_value=b'%PDF-1.4') as mock_pdf:
            resp = self._bulk(self.visit_with_report, self.foreign_visit)

        self.assertEqual(resp.status_code, 200)
        reports, = mock_pdf.call_args.args
        self.assertEqual([r.pk for r in reports], [self.report.pk])

    def test_bulk_export_skips_a_selected_visit_with_no_report(self):
        with patch(f'{PKG}.views.faculty.pdf_service.visit_letters_pdf',
                   return_value=b'%PDF-1.4') as mock_pdf:
            resp = self._bulk(self.visit_with_report, self.visit_without_report)

        self.assertEqual(resp.status_code, 200)
        reports, = mock_pdf.call_args.args
        self.assertEqual([r.pk for r in reports], [self.report.pk])

    def test_bulk_export_404s_when_nothing_resolves(self):
        with patch(f'{PKG}.views.faculty.pdf_service.visit_letters_pdf') as mock_pdf:
            resp = self._bulk(self.visit_without_report)

        self.assertEqual(resp.status_code, 404)
        mock_pdf.assert_not_called()

    def test_public_only_flag_reaches_the_pdf_service(self):
        with patch(f'{PKG}.views.faculty.pdf_service.visit_letters_pdf',
                   return_value=b'%PDF-1.4') as mock_pdf:
            self._bulk(self.visit_with_report, public_only='1')

        self.assertTrue(mock_pdf.call_args.kwargs['public_only'])

    # -- per-row download ----------------------------------------------------

    def _pdf_url(self, visit):
        return reverse('faculty_class_visit:report_pdf',
                       kwargs={'visit_id': visit.id})

    def test_per_row_download_returns_the_letter(self):
        with patch(f'{PKG}.views.faculty.pdf_service.visit_letter_pdf',
                   return_value=b'%PDF-1.4') as mock_pdf:
            resp = self.client.get(self._pdf_url(self.visit_with_report))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        mock_pdf.assert_called_once()

    def test_per_row_download_refuses_a_visit_outside_scope(self):
        with patch(f'{PKG}.views.faculty.pdf_service.visit_letter_pdf') as mock_pdf:
            resp = self.client.get(self._pdf_url(self.foreign_visit))

        self.assertEqual(resp.status_code, 404)
        mock_pdf.assert_not_called()

    def test_per_row_download_404s_when_there_is_no_report(self):
        with patch(f'{PKG}.views.faculty.pdf_service.visit_letter_pdf') as mock_pdf:
            resp = self.client.get(self._pdf_url(self.visit_without_report))

        self.assertEqual(resp.status_code, 404)
        mock_pdf.assert_not_called()

    # -- the table offers the download ---------------------------------------

    def test_visits_page_renders_a_download_button_for_rows_with_a_report(self):
        html = self.client.get(reverse('faculty_class_visit:visits')).content.decode()
        self.assertIn('report_pdf_url', html)
        self.assertIn("has_started_report === 'True'", html)

    def test_feed_serializes_the_pdf_url(self):
        resp = self.client.get(
            '/faculty/class_visits/api/visit_schedule/?format=json')
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        rows = rows['results'] if isinstance(rows, dict) else rows
        by_id = {r['id']: r for r in rows}
        self.assertIn(str(self.visit_with_report.id), by_id)
        self.assertIn('report_pdf_url',
                      by_id[str(self.visit_with_report.id)])
