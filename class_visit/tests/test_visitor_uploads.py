"""Visitor file uploads on the visit report, and who may download them.

Uploads reuse VisitReportFile: `kind='faculty_attachment'` marks a visitor's file,
`'instructor_response'` an instructor's (#14). Two settings: `visitor_file_upload`
(the report form accepts files) and `instructor_view_visitor_files` (the
instructor can see and download them on a submitted report).
"""
import datetime
import tempfile
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.course import Cohort, Course
from cis.models.section import ClassSection
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from . import PKG
from ..models import VisitReport, VisitReportFile, VisitSchedule
from ..services import uploads

User = get_user_model()

UPLOADS_ON = {'is_active': 'No', 'visitor_file_upload': 'Yes',
              'instructor_view_visitor_files': 'No'}
INSTRUCTOR_ON = {**UPLOADS_ON, 'instructor_view_visitor_files': 'Yes'}
OFF = {'is_active': 'No', 'visitor_file_upload': 'No',
       'instructor_view_visitor_files': 'No'}


def _sfx():
    return uuid.uuid4().hex[:8]


def _user(first, group=None):
    u = User.objects.create_user(
        username=f'{first}_{_sfx()}', email=f'{first}_{_sfx()}@x.com', password='x',
        first_name=first, last_name='Test')
    if group:
        u.groups.add(Group.objects.get_or_create(name=group)[0])
    return u


class _Fixture(TestCase):
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

        cls.instructor = _user('Ida', 'instructor')
        teacher = Teacher.objects.create(user=cls.instructor)
        cls.other_instructor = _user('Oscar', 'instructor')
        other_teacher = Teacher.objects.create(user=cls.other_instructor)

        section = ClassSection.objects.create(
            course=course, term=term, teacher=teacher,
            class_number=f'C-{_sfx()}', section_number='001')
        other_section = ClassSection.objects.create(
            course=course, term=term, teacher=other_teacher,
            class_number=f'C-{_sfx()}', section_number='002')

        cls.visitor = _user('Vera', 'faculty')
        cls.other_faculty = _user('Fred', 'faculty')
        cls.ce_user = _user('Cece', 'ce')

        cls.visit = VisitSchedule.objects.create(
            visit_date=datetime.date(2026, 3, 1), type_of_visit='Initial', meta={})
        cls.visit.class_sections.add(section)
        cls.visit.visitors.add(cls.visitor)

        cls.other_visit = VisitSchedule.objects.create(
            visit_date=datetime.date(2026, 3, 1), type_of_visit='Initial', meta={})
        cls.other_visit.class_sections.add(other_section)
        cls.other_visit.visitors.add(cls.visitor)

    def setUp(self):
        # PrivateMediaStorage is S3; tests have no bucket.
        field = VisitReportFile._meta.get_field('file')
        patcher = patch.object(
            field, 'storage', FileSystemStorage(location=tempfile.mkdtemp()))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = Client(REMOTE_ADDR='127.0.0.1')

    def _settings(self, cfg):
        patcher = patch(f'{PKG}.settings.class_visit.class_visit.from_db', return_value=cfg)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _report(self, status='Submitted', visit=None):
        return VisitReport.objects.create(
            visit_schedule=visit or self.visit, status=status, meta={})

    def _file(self, report, kind=VisitReportFile.FACULTY_ATTACHMENT, name='notes.pdf'):
        f = VisitReportFile(visit_report=report, kind=kind, uploaded_by=self.visitor)
        f.file.save(name, ContentFile(b'data'), save=True)
        return f


class SettingsTest(TestCase):
    def test_fields_exist(self):
        from ..settings.class_visit import class_visit as S
        self.assertIn('visitor_file_upload', S.base_fields)
        self.assertIn('instructor_view_visitor_files', S.base_fields)

    def test_install_seeds_both_off(self):
        from cis.models.settings import Setting
        from ..settings.class_visit import class_visit as S
        Setting.objects.filter(key=S.key).delete()
        S().install()
        value = Setting.objects.get(key=S.key).value
        self.assertEqual(value['visitor_file_upload'], 'No')
        self.assertEqual(value['instructor_view_visitor_files'], 'No')


class ReportFormUploadTest(_Fixture):
    def _url(self):
        return reverse('faculty_class_visit:edit_visit_report',
                       kwargs={'visit_id': self.visit.id})

    def test_no_upload_field_when_off(self):
        self._settings(OFF)
        self.client.force_login(self.visitor)
        html = self.client.get(self._url()).content.decode()
        self.assertNotIn(f'name="{uploads.FIELD_NAME}"', html)

    def test_draft_post_stores_visitor_files(self):
        self._settings(UPLOADS_ON)
        self.client.force_login(self.visitor)
        resp = self.client.post(self._url(), {
            'submit_action': 'draft',
            uploads.FIELD_NAME: [
                SimpleUploadedFile('a.pdf', b'one'),
                SimpleUploadedFile('photo.jpg', b'two'),
            ],
        })
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.json()['refresh'])
        files = VisitReportFile.objects.filter(visit_report__visit_schedule=self.visit)
        self.assertEqual(files.count(), 2)
        for f in files:
            self.assertEqual(f.kind, VisitReportFile.FACULTY_ATTACHMENT)
            self.assertEqual(f.uploaded_by_id, self.visitor.id)

    def test_upload_field_rendered_when_on(self):
        self._settings(UPLOADS_ON)
        self.client.force_login(self.visitor)
        html = self.client.get(self._url()).content.decode()
        self.assertIn(f'name="{uploads.FIELD_NAME}"', html)
        self.assertIn('multipart/form-data', html)

    def test_disallowed_type_rejected_and_nothing_saved(self):
        self._settings(UPLOADS_ON)
        self.client.force_login(self.visitor)
        resp = self.client.post(self._url(), {
            'submit_action': 'draft',
            uploads.FIELD_NAME: [SimpleUploadedFile('run.exe', b'MZ')],
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn('run.exe', resp.json()['message'])
        self.assertFalse(VisitReport.objects.filter(visit_schedule=self.visit).exists())

    def test_oversized_file_rejected(self):
        self._settings(UPLOADS_ON)
        self.client.force_login(self.visitor)
        big = SimpleUploadedFile('big.pdf', b'x' * (uploads.MAX_UPLOAD_BYTES + 1))
        resp = self.client.post(self._url(), {
            'submit_action': 'draft', uploads.FIELD_NAME: [big]})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(VisitReportFile.objects.count(), 0)


class DownloadAccessTest(_Fixture):
    def _get(self, user, name, report_file, visit=None):
        self.client.force_login(user)
        return self.client.get(reverse(name, kwargs={
            'visit_id': (visit or self.visit).id, 'file_id': report_file.id}))

    def test_ce_and_visitor_download(self):
        self._settings(OFF)  # turning uploads off later keeps existing files reachable
        f = self._file(self._report())
        self.assertEqual(self._get(self.ce_user, 'class_visit:ce_download_file', f).status_code, 200)
        resp = self._get(self.visitor, 'faculty_class_visit:download_file', f)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('attachment', resp['Content-Disposition'])

    def test_unrelated_faculty_refused(self):
        self._settings(UPLOADS_ON)
        f = self._file(self._report())
        resp = self._get(self.other_faculty, 'faculty_class_visit:download_file', f)
        self.assertEqual(resp.status_code, 404)

    def test_file_from_another_visit_refused(self):
        self._settings(INSTRUCTOR_ON)
        f = self._file(self._report(visit=self.other_visit))
        # Valid visit in the URL, but the file belongs to a different visit.
        for user, name in ((self.visitor, 'faculty_class_visit:download_file'),
                           (self.ce_user, 'class_visit:ce_download_file'),
                           (self.instructor, 'instructor_class_visit:download_file')):
            self.assertEqual(self._get(user, name, f).status_code, 404, name)

    def test_instructor_refused_when_setting_off(self):
        self._settings(UPLOADS_ON)
        f = self._file(self._report())
        resp = self._get(self.instructor, 'instructor_class_visit:download_file', f)
        self.assertEqual(resp.status_code, 404)

    def test_instructor_downloads_when_on_and_submitted(self):
        self._settings(INSTRUCTOR_ON)
        f = self._file(self._report())
        resp = self._get(self.instructor, 'instructor_class_visit:download_file', f)
        self.assertEqual(resp.status_code, 200)

    def test_instructor_refused_on_draft(self):
        self._settings(INSTRUCTOR_ON)
        f = self._file(self._report(status='Draft'))
        resp = self._get(self.instructor, 'instructor_class_visit:download_file', f)
        self.assertEqual(resp.status_code, 404)

    def test_other_instructor_refused(self):
        self._settings(INSTRUCTOR_ON)
        f = self._file(self._report())
        resp = self._get(self.other_instructor, 'instructor_class_visit:download_file', f)
        self.assertEqual(resp.status_code, 404)

    def test_instructor_always_gets_own_response_file(self):
        self._settings(UPLOADS_ON)
        f = self._file(self._report(), kind=VisitReportFile.INSTRUCTOR_RESPONSE)
        resp = self._get(self.instructor, 'instructor_class_visit:download_file', f)
        self.assertEqual(resp.status_code, 200)


class ListingTest(_Fixture):
    def _instructor_html(self):
        self.client.force_login(self.instructor)
        return self.client.get(reverse(
            'instructor_class_visit:report_detail',
            kwargs={'visit_id': self.visit.id})).content.decode()

    def test_instructor_page_lists_visitor_files_only_when_on(self):
        self._file(self._report(), name='evidence.pdf')
        self._settings(UPLOADS_ON)
        self.assertNotIn('evidence', self._instructor_html())
        patch.stopall()
        self._settings(INSTRUCTOR_ON)
        self.assertIn('evidence', self._instructor_html())

    def test_ce_report_page_lists_files(self):
        self._settings(OFF)
        self._file(self._report(), name='evidence.pdf')
        self.client.force_login(self.ce_user)
        html = self.client.get(reverse(
            'class_visit:ce_view_report', kwargs={'visit_id': self.visit.id})).content.decode()
        self.assertIn('evidence', html)
        self.assertIn('Visitor attachment', html)


class RemoveTest(_Fixture):
    def _remove(self, user, report_file):
        self.client.force_login(user)
        return self.client.post(reverse('faculty_class_visit:remove_file', kwargs={
            'visit_id': self.visit.id, 'file_id': report_file.id}))

    def test_visitor_removes_from_draft(self):
        self._settings(UPLOADS_ON)
        f = self._file(self._report(status='Draft'))
        self.assertEqual(self._remove(self.visitor, f).status_code, 200)
        self.assertFalse(VisitReportFile.objects.filter(pk=f.pk).exists())

    def test_cannot_remove_after_submit(self):
        self._settings(UPLOADS_ON)
        f = self._file(self._report(status='Submitted'))
        self.assertEqual(self._remove(self.visitor, f).status_code, 400)
        self.assertTrue(VisitReportFile.objects.filter(pk=f.pk).exists())

    def test_cannot_remove_instructor_file(self):
        self._settings(UPLOADS_ON)
        f = self._file(self._report(status='Draft'), kind=VisitReportFile.INSTRUCTOR_RESPONSE)
        self.assertEqual(self._remove(self.visitor, f).status_code, 400)

    def test_get_not_allowed(self):
        self._settings(UPLOADS_ON)
        f = self._file(self._report(status='Draft'))
        self.client.force_login(self.visitor)
        resp = self.client.get(reverse('faculty_class_visit:remove_file', kwargs={
            'visit_id': self.visit.id, 'file_id': f.id}))
        self.assertEqual(resp.status_code, 405)
