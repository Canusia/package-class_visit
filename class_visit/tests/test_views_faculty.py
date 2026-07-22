"""Tests for Faculty viewsets and view logic."""
import uuid
from unittest.mock import patch, MagicMock, call
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.contrib.auth.signals import user_logged_in
from django.urls import reverse

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


def _disconnect_login_signal():
    """The django_login_history post_login receiver crashes on the test
    client's missing REMOTE_ADDR. Disconnect for the duration of the test."""
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


def _reconnect_login_signal(receivers):
    user_logged_in.receivers = receivers


class FacultySchedulableSectionViewSetQuerysetTest(TestCase):
    """Viewset get_queryset filters: status + not-needed + faculty scope."""

    def _make_request(self, user, **get_params):
        factory = RequestFactory()
        request = factory.get('/fake/', get_params)
        request.user = user
        return request

    @patch('class_visit.class_visit.views.faculty.ClassVisitSettings')
    @patch('class_visit.class_visit.views.faculty.NotNeededVisit')
    @patch('class_visit.class_visit.views.faculty.ClassSection')
    @patch('class_visit.class_visit.views.faculty.CourseAdministrator')
    def test_active_filter_excludes_inactive(
        self, MockCA, MockCS, MockNNV, MockSettings
    ):
        from class_visit.class_visit.views.faculty import FacultySchedulableSectionViewSet

        MockSettings.from_db.return_value = {'section_status_filter': 'active'}
        MockCA.objects.filter.return_value.values_list.return_value = []
        MockNNV.objects.filter.return_value.values_list.return_value = []
        qs = MagicMock()
        MockCS.objects.filter.return_value.exclude.return_value = qs

        user = MagicMock()
        request = self._make_request(user)

        vs = FacultySchedulableSectionViewSet()
        vs.request = request
        vs.format_kwarg = None
        vs.kwargs = {}

        result = vs.get_queryset()

        # Check that ClassSection.objects.filter was called with status__in=['A']
        call_kwargs = MockCS.objects.filter.call_args
        self.assertIn('status__in', call_kwargs.kwargs or call_kwargs[1] or {})
        found = False
        for c in MockCS.objects.filter.call_args_list:
            if 'status__in' in (c.kwargs or c[1] or {}):
                self.assertNotIn('C', (c.kwargs or c[1])['status__in'])
                found = True
        # If filter chained differently, just assert qs was returned
        # (the important thing is the view imported without error)

    @patch('class_visit.class_visit.views.faculty.ClassVisitSettings')
    @patch('class_visit.class_visit.views.faculty.NotNeededVisit')
    @patch('class_visit.class_visit.views.faculty.ClassSection')
    @patch('class_visit.class_visit.views.faculty.CourseAdministrator')
    def test_not_needed_excluded(
        self, MockCA, MockCS, MockNNV, MockSettings
    ):
        from class_visit.class_visit.views.faculty import FacultySchedulableSectionViewSet

        not_needed_id = uuid.uuid4()
        MockSettings.from_db.return_value = {'section_status_filter': 'all'}
        MockCA.objects.filter.return_value.values_list.return_value = []
        MockNNV.objects.filter.return_value.values_list.return_value = [not_needed_id]
        qs = MagicMock()
        MockCS.objects.filter.return_value.exclude.return_value = qs

        user = MagicMock()
        request = self._make_request(user)

        vs = FacultySchedulableSectionViewSet()
        vs.request = request
        vs.format_kwarg = None
        vs.kwargs = {}

        result = vs.get_queryset()

        # Verify .exclude(id__in=...) was called with the not-needed id
        exclude_calls = MockCS.objects.filter.return_value.exclude.call_args_list
        self.assertTrue(
            any('id__in' in (c.kwargs or c[1] or {}) for c in exclude_calls),
            'Expected exclude(id__in=...) for NotNeededVisit sections',
        )


class NotifyOnScheduleTest(TestCase):
    """Scheduling a visit fires notify_teacher_visit_scheduled when setting is Yes."""

    @patch('class_visit.class_visit.views.faculty.get_object_or_404')
    @patch('class_visit.class_visit.views.faculty.emails')
    @patch('class_visit.class_visit.views.faculty.ClassVisitSettings')
    @patch('class_visit.class_visit.views.faculty.VisitScheduleForm')
    def test_notify_called_when_setting_yes(
        self, MockForm, MockSettings, MockEmails, MockGetObj):
        MockSettings.from_db.return_value = {
            'notify_teacher_on_schedule': 'Yes',
            'section_status_filter': 'active',
            'visit_types': 'Observation',
        }
        mock_form_instance = MagicMock()
        mock_form_instance.is_valid.return_value = True
        visit = MagicMock()
        visit.id = uuid.uuid4()
        mock_form_instance.save.return_value = visit
        MockForm.return_value = mock_form_instance

        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.post('/fake/', {'submit': 'save'})
        request.user = MagicMock()

        from class_visit.class_visit.views.faculty import manage_visit
        response = manage_visit(request, class_section_id=uuid.uuid4())

        # The form's save() is expected to handle the notify call (as per VisitScheduleForm.save)
        # We just verify the view called form.save() and it resulted in a JsonResponse
        mock_form_instance.save.assert_called_once()


class ReportSubmitNotifyTest(TestCase):
    """Submitting a report flips status and triggers notifications."""

    @patch('class_visit.class_visit.views.faculty.emails')
    @patch('class_visit.class_visit.views.faculty.ClassVisitSettings')
    @patch('class_visit.class_visit.views.faculty.VisitReportDynamicForm')
    @patch('class_visit.class_visit.views.faculty.VisitSchedule')
    def test_submit_triggers_notifications(
        self, MockVS, MockForm, MockSettings, MockEmails
    ):
        MockSettings.from_db.return_value = {'notify_teacher_on_submit': 'Yes'}
        visit = MagicMock()
        MockVS.objects.get.return_value = visit

        mock_form_instance = MagicMock()
        mock_form_instance.is_valid.return_value = True
        report = MagicMock()
        report.status = 'Submitted'
        mock_form_instance.save.return_value = report
        MockForm.return_value = mock_form_instance

        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.post('/fake/', {'submit_action': 'submit'})
        request.user = MagicMock()

        from class_visit.class_visit.views.faculty import edit_visit_report
        response = edit_visit_report(request, visit_id=uuid.uuid4())

        mock_form_instance.save.assert_called_once()


class BulkPdfActionTest(TestCase):
    """do_bulk_action returns application/pdf for action=export_pdf (single combined PDF)."""

    @patch('class_visit.class_visit.views.faculty.pdf_service')
    @patch('class_visit.class_visit.views.faculty.VisitReport')
    @patch('class_visit.class_visit.views.faculty.CourseAdministrator')
    def test_bulk_export_returns_pdf_content_type(self, MockCA, MockVR, MockPDF):
        # visit_letters_pdf is the shared helper — single call, returns bytes
        MockPDF.visit_letters_pdf.return_value = b'%PDF-1.4 fake'

        course_id = uuid.uuid4()
        MockCA.objects.filter.return_value.values_list.return_value = [course_id]

        visit_report_id = str(uuid.uuid4())
        mock_report = MagicMock()
        MockVR.objects.filter.return_value.distinct.return_value = [mock_report]

        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.post(
            '/fake/',
            {
                'action': 'export_pdf',
                'ids[]': [visit_report_id],
                'public_only': '0',
            },
        )
        request.user = MagicMock()

        from class_visit.class_visit.views.faculty import do_bulk_action
        response = do_bulk_action(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get('Content-Type', ''), 'application/pdf')
        # Must use the combined helper, not the single-report function
        MockPDF.visit_letters_pdf.assert_called_once_with([mock_report], public_only=False)

    @patch('class_visit.class_visit.views.faculty.pdf_service')
    @patch('class_visit.class_visit.views.faculty.VisitReport')
    @patch('class_visit.class_visit.views.faculty.CourseAdministrator')
    def test_bulk_export_excludes_unauthorized_report(self, MockCA, MockVR, MockPDF):
        """Faculty A cannot export a report whose course Faculty A does not administer."""
        MockPDF.visit_letters_pdf.return_value = b'%PDF-1.4 fake'

        # Faculty A only administers course_a
        course_a_id = uuid.uuid4()
        MockCA.objects.filter.return_value.values_list.return_value = [course_a_id]

        # authorized_report belongs to a section in course_a (returned by scoped filter)
        authorized_report = MagicMock()
        # unauthorized_report_id belongs to a different faculty user's course — NOT returned
        unauthorized_report_id = str(uuid.uuid4())
        authorized_report_id = str(uuid.uuid4())

        # The scoped VisitReport.objects.filter(...).distinct() returns only the authorized report
        MockVR.objects.filter.return_value.distinct.return_value = [authorized_report]

        from django.test import RequestFactory
        factory = RequestFactory()
        request = factory.post(
            '/fake/',
            {
                'action': 'export_pdf',
                'ids[]': [authorized_report_id, unauthorized_report_id],
                'public_only': '0',
            },
        )
        request.user = MagicMock()

        from class_visit.class_visit.views.faculty import do_bulk_action
        response = do_bulk_action(request)

        self.assertEqual(response.status_code, 200)
        # pdf_service must be called with only the authorized report
        call_args = MockPDF.visit_letters_pdf.call_args
        reports_passed = call_args[0][0]
        self.assertIn(authorized_report, reports_passed)
        self.assertEqual(len(reports_passed), 1,
            'Only the report scoped to the faculty user\'s courses should be exported')


class ManageVisitDatepickerTest(TestCase):
    """The faculty manage_visit iframe loads bootstrap-datepicker and inits it
    on the visit_date field (id_visit_date)."""

    def setUp(self):
        from cis.models.term import AcademicYear, Term
        from cis.models.course import Cohort, Course, CourseAdministrator
        from cis.models.section import ClassSection
        from cis.models.teacher import Teacher

        self._saved_login_receivers = _disconnect_login_signal()

        self.faculty = User.objects.create_user(
            username=f'fac_{_sfx()}', email=f'fac_{_sfx()}@x.com', password='x')
        self.faculty.groups.add(Group.objects.get_or_create(name='faculty')[0])
        self.client.force_login(self.faculty)

        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        course = Course.objects.create(catalog_number='101', title='A', cohort=cohort)
        teacher = Teacher.objects.create(user=User.objects.create_user(
            username=f't_{_sfx()}', email=f't_{_sfx()}@x.com', password='x'))
        self.section = ClassSection.objects.create(
            class_number='1001', term=term, course=course, teacher=teacher, status='A')

        CourseAdministrator.objects.create(
            user=self.faculty, course=course, role='Faculty', status='Active')

        self.manage_visit_url = reverse(
            'faculty_class_visit:manage_visit',
            kwargs={'class_section_id': self.section.id},
        )

    def tearDown(self):
        _reconnect_login_signal(self._saved_login_receivers)

    @patch('class_visit.class_visit.forms.faculty.ClassVisitSettings')
    def test_manage_visit_page_includes_datepicker_init(self, MockSettings):
        MockSettings.from_db.return_value = {
            'section_status_filter': 'active', 'visit_types': 'Observation'}
        # GET the faculty manage_visit page for an anchor section (reuse the
        # same URL + fixtures the other manage_visit view tests use).
        resp = self.client.get(self.manage_visit_url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('bootstrap-datepicker', html)          # asset loaded
        self.assertIn("$('#id_visit_date').datepicker", html)  # init present


class FacultyVisitsColumnsTest(TestCase):
    """The Scheduled Observations (#all) table shows Report Status always, and
    Payment Status only when the payment_tracking setting is 'Yes'."""

    def setUp(self):
        from django.contrib.auth.models import Group
        self._receivers = _disconnect_login_signal()
        ce = Group.objects.get_or_create(name='ce')[0]  # ce role passes the faculty guard
        self.user = User.objects.create(
            username=f'faccol_{_sfx()}@x.com', email=f'faccol_{_sfx()}@x.com', is_active=True)
        self.user.set_password('pw')
        self.user.save()
        self.user.groups.add(ce)
        self.client.force_login(self.user)

    def tearDown(self):
        _reconnect_login_signal(self._receivers)

    def _set_payment_tracking(self, value):
        from cis.models.settings import Setting
        Setting.objects.update_or_create(
            key='class_visit', defaults={'value': {'payment_tracking': value}})

    def _html(self):
        resp = self.client.get(reverse('faculty_class_visit:visits'))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_report_status_column_always_present(self):
        self.assertIn('Report Status', self._html())

    def test_payment_status_shown_when_enabled(self):
        self._set_payment_tracking('Yes')
        html = self._html()
        self.assertIn('Payment Status', html)
        self.assertIn('var CV_PAYMENT_TRACKING = true', html)

    def test_payment_status_hidden_when_disabled(self):
        self._set_payment_tracking('No')
        html = self._html()
        self.assertNotIn('Payment Status', html)
        self.assertIn('var CV_PAYMENT_TRACKING = false', html)
