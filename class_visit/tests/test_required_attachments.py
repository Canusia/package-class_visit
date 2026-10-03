"""Required attachments: visitor on submit, instructor on sign-off.

`visitor_file_required` (with `visitor_file_upload`) blocks Submit -- never Save
as Draft (#11) -- until the report has a visitor file. `instructor_file_required`
(with `instructor_signature`) blocks any sign-off / response POST until the
instructor has a response file on the report.
"""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ..models import VisitReport, VisitReportFile
from ..services import uploads
from .test_visitor_uploads import _Fixture

BASE = {'is_active': 'No', 'visitor_file_upload': 'Yes',
        'instructor_view_visitor_files': 'No', 'visitor_file_required': 'Yes',
        'instructor_signature': 'Yes', 'instructor_file_required': 'No'}
INSTRUCTOR_REQUIRED = {**BASE, 'visitor_file_required': 'No',
                       'instructor_file_required': 'Yes'}


class VisitorFileRequiredTest(_Fixture):
    def _post(self, action, files=None):
        self.client.force_login(self.visitor)
        data = {'submit_action': action}
        if files:
            data[uploads.FIELD_NAME] = files
        return self.client.post(reverse(
            'faculty_class_visit:edit_visit_report',
            kwargs={'visit_id': self.visit.id}), data)

    def test_submit_without_file_rejected(self):
        self._settings(BASE)
        resp = self._post('submit')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Attach at least one file', resp.json()['message'])
        self.assertFalse(VisitReport.objects.filter(
            visit_schedule=self.visit, status='Submitted').exists())

    def test_draft_without_file_saved(self):
        self._settings(BASE)
        self.assertEqual(self._post('draft').status_code, 200)

    def test_submit_with_new_file_accepted(self):
        self._settings(BASE)
        resp = self._post('submit', [SimpleUploadedFile('form.pdf', b'x')])
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self.visit.report.status, 'Submitted')

    def test_submit_with_existing_file_accepted(self):
        self._settings(BASE)
        self._file(self._report(status='Draft'))
        self.assertEqual(self._post('submit').status_code, 200)

    def test_instructor_file_does_not_satisfy_visitor_requirement(self):
        self._settings(BASE)
        self._file(self._report(status='Draft'), kind=VisitReportFile.INSTRUCTOR_RESPONSE)
        self.assertEqual(self._post('submit').status_code, 400)

    def test_ignored_when_uploads_off(self):
        self._settings({**BASE, 'visitor_file_upload': 'No'})
        self.assertEqual(self._post('submit').status_code, 200)

    def test_label_says_required(self):
        self._settings(BASE)
        self.client.force_login(self.visitor)
        html = self.client.get(reverse(
            'faculty_class_visit:edit_visit_report',
            kwargs={'visit_id': self.visit.id})).content.decode()
        self.assertIn('required to submit', html)


class InstructorFileRequiredTest(_Fixture):
    def setUp(self):
        super().setUp()
        self.report = self._report()
        self.client.force_login(self.instructor)
        self.url = reverse('instructor_class_visit:sign_report',
                           kwargs={'visit_id': self.visit.id})

    def test_sign_without_file_refused_and_nothing_written(self):
        self._settings(INSTRUCTOR_REQUIRED)
        resp = self.client.post(self.url, {
            'instructor_signature': 'Ida', 'instructor_response': 'ok'})
        self.assertEqual(resp.status_code, 302)
        self.assertIn('signoff_error=file_required', resp['Location'])
        self.report.refresh_from_db()
        self.assertEqual(self.report.instructor_signature, '')
        self.assertEqual(self.report.instructor_response, '')

    def test_error_shown_on_page(self):
        self._settings(INSTRUCTOR_REQUIRED)
        html = self.client.get(reverse(
            'instructor_class_visit:report_detail', kwargs={'visit_id': self.visit.id}),
            {'signoff_error': 'file_required'}).content.decode()
        self.assertIn('Attach a file to sign or respond', html)
        self.assertIn('(required)', html)

    def test_sign_with_file_accepted(self):
        self._settings(INSTRUCTOR_REQUIRED)
        self.client.post(self.url, {
            'instructor_signature': 'Ida',
            'response_file': SimpleUploadedFile('reply.pdf', b'x')})
        self.report.refresh_from_db()
        self.assertEqual(self.report.instructor_signature, 'Ida')
        self.assertTrue(self.report.files.filter(
            kind=VisitReportFile.INSTRUCTOR_RESPONSE).exists())

    def test_earlier_response_file_satisfies(self):
        self._settings(INSTRUCTOR_REQUIRED)
        self._file(self.report, kind=VisitReportFile.INSTRUCTOR_RESPONSE)
        self.client.post(self.url, {'instructor_signature': 'Ida'})
        self.report.refresh_from_db()
        self.assertEqual(self.report.instructor_signature, 'Ida')

    def test_not_required_by_default(self):
        self._settings({**INSTRUCTOR_REQUIRED, 'instructor_file_required': 'No'})
        self.client.post(self.url, {'instructor_signature': 'Ida'})
        self.report.refresh_from_db()
        self.assertEqual(self.report.instructor_signature, 'Ida')
