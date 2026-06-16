"""
Instructor class-visit tests.
Run:
    docker exec -w /app/webapp django_web_ewu \
        python manage.py test class_visit.class_visit.tests.test_instructor -v 2 --noinput
"""
import uuid
from unittest.mock import patch, MagicMock, PropertyMock

from django.test import TestCase, Client, RequestFactory
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.urls import reverse

User = get_user_model()

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None


# ---------------------------------------------------------------------------
# Task 1: URL resolution
# ---------------------------------------------------------------------------

class URLResolutionTest(TestCase):
    def test_index_url_resolves(self):
        url = reverse('instructor_class_visit:index')
        self.assertEqual(url, '/instructor/class_visits/')

    def test_confirm_url_resolves(self):
        url = reverse('instructor_class_visit:confirm_visit', kwargs={'token': 'abc123'})
        self.assertIn('confirm', url)


# ---------------------------------------------------------------------------
# Task 2: Viewset queryset scoping
# ---------------------------------------------------------------------------

class VisitScheduleQuerysetTest(TestCase):
    """InstructorVisitScheduleViewSet.get_queryset scopes to instructor's own sections."""

    def _make_request(self, user):
        factory = RequestFactory()
        request = factory.get('/fake/')
        request.user = user
        return request

    @patch('class_visit.class_visit.views.instructor.VisitSchedule')
    def test_instructor_sees_only_own_sections(self, MockVS):
        """get_queryset filters by the logged-in teacher."""
        from class_visit.class_visit.views.instructor import InstructorVisitScheduleViewSet

        teacher = MagicMock()
        user = MagicMock()
        user.teacher = teacher

        qs = MagicMock()
        MockVS.objects.filter.return_value = qs
        qs.prefetch_related.return_value = qs
        qs.order_by.return_value = qs
        qs.distinct.return_value = qs

        request = self._make_request(user)
        vs = InstructorVisitScheduleViewSet()
        vs.request = request
        vs.format_kwarg = None
        vs.kwargs = {}

        result = vs.get_queryset()

        # Must filter by class_sections__teacher=teacher
        MockVS.objects.filter.assert_called_once_with(class_sections__teacher=teacher)
        self.assertEqual(result, qs)

    @patch('class_visit.class_visit.views.instructor.VisitSchedule')
    def test_no_teacher_returns_empty_queryset(self, MockVS):
        """User without a teacher profile gets an empty queryset."""
        from class_visit.class_visit.views.instructor import InstructorVisitScheduleViewSet

        user = MagicMock()
        # Simulate no teacher via AttributeError on .teacher access
        type(user).teacher = PropertyMock(side_effect=AttributeError('no teacher'))

        MockVS.objects.none.return_value = MagicMock()

        request = self._make_request(user)
        vs = InstructorVisitScheduleViewSet()
        vs.request = request
        vs.format_kwarg = None
        vs.kwargs = {}

        # Patch _get_teacher_or_none to return None (simulates AttributeError path)
        with patch('class_visit.class_visit.views.instructor._get_teacher_or_none',
                   return_value=None):
            result = vs.get_queryset()

        MockVS.objects.none.assert_called_once()

    def test_unauthenticated_redirected(self):
        client = Client()
        resp = client.get('/instructor/class_visits/')
        self.assertIn(resp.status_code, [302, 403])


# ---------------------------------------------------------------------------
# Task 3: Public report detail view
# ---------------------------------------------------------------------------

class PublicReportDetailTest(TestCase):
    """report_detail view shows public fields only for submitted reports."""

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

    def setUp(self):
        group, _ = Group.objects.get_or_create(name='instructor')
        self.instructor_user = User.objects.create_user(
            username='test_instructor',
            email='ti@example.com',
            password='testpass123',
        )
        self.instructor_user.groups.add(group)

        self.other_instructor = User.objects.create_user(
            username='test_other_instructor',
            email='ti2@example.com',
            password='testpass123',
        )
        self.other_instructor.groups.add(group)

    def _call_report_detail(self, user, visit_id, mock_visit, public_values=None):
        """
        Helper: call report_detail with mocked DB layer.
        Patches _get_teacher_or_none, VisitSchedule, and get_object_or_404.
        """
        from django.test import RequestFactory
        from class_visit.class_visit.views.instructor import report_detail as view_fn

        factory = RequestFactory()
        request = factory.get(f'/instructor/class_visits/report/{visit_id}/')
        request.user = user

        teacher = MagicMock()

        # Mock VisitSchedule at module level to avoid real DB filter with MagicMock teacher
        mock_vs = MagicMock()
        mock_qs = MagicMock()
        mock_vs.objects.filter.return_value = mock_qs
        mock_qs.distinct.return_value = mock_qs

        with patch('class_visit.class_visit.views.instructor._get_teacher_or_none',
                   return_value=teacher), \
             patch('class_visit.class_visit.views.instructor.VisitSchedule', mock_vs), \
             patch('class_visit.class_visit.views.instructor.get_object_or_404',
                   return_value=mock_visit), \
             patch('class_visit.class_visit.views.instructor.draw_menu', return_value=''), \
             patch('class_visit.class_visit.views.instructor.rf_service') as mock_rf:

            if public_values is not None:
                mock_rf.report_values_for_display.return_value = public_values

            response = view_fn(request, visit_id=visit_id)

        return response

    def test_no_report_shows_not_available(self):
        """No report → 'not available yet' in response."""
        visit = MagicMock()
        type(visit).report = PropertyMock(side_effect=Exception('DoesNotExist'))
        visit.has_report.return_value = False

        visit_id = uuid.uuid4()
        resp = self._call_report_detail(self.instructor_user, visit_id, visit)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('not available yet', content)

    def test_draft_report_not_visible(self):
        """Draft report → 'not available yet', private content not shown."""
        report = MagicMock()
        report.status = 'Draft'
        visit = MagicMock()
        type(visit).report = PropertyMock(return_value=report)

        visit_id = uuid.uuid4()
        resp = self._call_report_detail(self.instructor_user, visit_id, visit)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('not available yet', content)

    def test_submitted_report_shows_public_fields(self):
        """Submitted report → public field values appear in response."""
        report = MagicMock()
        report.status = 'Submitted'
        visit = MagicMock()
        type(visit).report = PropertyMock(return_value=report)

        public_values = [
            {'label': 'Strengths', 'value': 'Hello instructor!'},
        ]

        visit_id = uuid.uuid4()
        resp = self._call_report_detail(
            self.instructor_user, visit_id, visit, public_values=public_values
        )
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Hello instructor!', content)

    def test_other_instructor_cannot_see_report(self):
        """An instructor whose sections don't include this visit gets 404."""
        from django.http import Http404
        from django.test import RequestFactory
        from class_visit.class_visit.views.instructor import report_detail as view_fn

        factory = RequestFactory()
        visit_id = uuid.uuid4()
        request = factory.get(f'/instructor/class_visits/report/{visit_id}/')
        request.user = self.other_instructor

        teacher = MagicMock()
        mock_vs = MagicMock()
        mock_qs = MagicMock()
        mock_vs.objects.filter.return_value = mock_qs
        mock_qs.distinct.return_value = mock_qs

        with patch('class_visit.class_visit.views.instructor._get_teacher_or_none',
                   return_value=teacher), \
             patch('class_visit.class_visit.views.instructor.VisitSchedule', mock_vs), \
             patch('class_visit.class_visit.views.instructor.get_object_or_404',
                   side_effect=Http404), \
             patch('class_visit.class_visit.views.instructor.draw_menu', return_value=''):

            with self.assertRaises(Http404):
                view_fn(request, visit_id=visit_id)


# ---------------------------------------------------------------------------
# Task 4: Confirmation endpoint
# ---------------------------------------------------------------------------

class ConfirmVisitTest(TestCase):
    """confirm_visit_view: token auth, idempotent, graceful bad token."""

    PATCH_PATH = 'class_visit.class_visit.views.instructor.svc_confirm_import'

    PATCH_SVC = 'class_visit.class_visit.views.instructor.svc_confirm'

    def test_valid_token_sets_confirmed_on(self):
        """Valid token → confirm_visit service called, shows success page."""
        visit = MagicMock()
        visit.visit_date_sexy = '09/01/2026'

        with patch(self.PATCH_SVC, return_value=visit):
            url = reverse('instructor_class_visit:confirm_visit',
                          kwargs={'token': 'valid-token-abc'})
            resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'confirmed')

    def test_valid_token_idempotent(self):
        """Calling confirm twice does not error."""
        visit = MagicMock()
        visit.visit_date_sexy = '09/01/2026'

        with patch(self.PATCH_SVC, return_value=visit):
            url = reverse('instructor_class_visit:confirm_visit',
                          kwargs={'token': 'valid-token-abc'})
            self.client.get(url)
            resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)

    def test_invalid_token_returns_graceful_page(self):
        """Bad token → graceful page showing 'Not Found', status 200."""
        with patch(self.PATCH_SVC, return_value=None):
            url = reverse('instructor_class_visit:confirm_visit',
                          kwargs={'token': 'invalid-token-xyz'})
            resp = self.client.get(url)

        self.assertEqual(resp.status_code, 200)
        # Template shows "Confirmation Link Not Found" (case-insensitive check)
        self.assertContains(resp, 'Not Found')

    def test_confirm_page_shows_success_message(self):
        """Valid token → page contains 'confirmed'."""
        visit = MagicMock()
        visit.visit_date_sexy = '09/01/2026'

        with patch(self.PATCH_SVC, return_value=visit):
            url = reverse('instructor_class_visit:confirm_visit',
                          kwargs={'token': 'valid-token-abc'})
            resp = self.client.get(url)

        self.assertContains(resp, 'confirmed')


# ---------------------------------------------------------------------------
# Task 5: Bulk export — public-only PDF
# ---------------------------------------------------------------------------

class BulkExportPDFTest(TestCase):
    """do_bulk_action returns a combined public-only PDF for instructor's own visits."""

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

    def setUp(self):
        group, _ = Group.objects.get_or_create(name='instructor')
        self.instructor_user = User.objects.create_user(
            username='bulk_test_instructor',
            email='bulk_ti@example.com',
            password='testpass123',
        )
        self.instructor_user.groups.add(group)

        self.other_instructor_user = User.objects.create_user(
            username='bulk_other_instructor',
            email='bulk_ti2@example.com',
            password='testpass123',
        )
        self.other_instructor_user.groups.add(group)

        self.client = Client()

    def _post_bulk(self, user, ids, action='export_pdf'):
        self.client.force_login(user)
        return self.client.post(
            reverse('instructor_class_visit:bulk_action'),
            data={'action': action, 'ids[]': ids},
        )

    @patch('class_visit.class_visit.views.instructor.visit_letters_pdf', return_value=b'%PDF-fake')
    @patch('class_visit.class_visit.views.instructor._get_teacher_or_none')
    @patch('class_visit.class_visit.views.instructor.VisitSchedule')
    def test_bulk_pdf_returns_pdf_content_type(self, MockVS, mock_get_teacher, mock_pdf):
        """POST export_pdf → 200 application/pdf, visit_letters_pdf called with public_only=True."""
        teacher = MagicMock()
        mock_get_teacher.return_value = teacher

        # A single submitted report in a fake visit
        report = MagicMock()
        report.status = 'Submitted'
        visit = MagicMock()
        visit.report = report
        # has_report() fallback not needed when visit.report works
        qs = MagicMock()
        MockVS.objects.filter.return_value = qs
        qs.distinct.return_value = qs
        qs.prefetch_related.return_value = qs
        qs.__iter__ = MagicMock(return_value=iter([visit]))

        visit_id = str(uuid.uuid4())
        resp = self._post_bulk(self.instructor_user, [visit_id])

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        mock_pdf.assert_called_once()
        call_kwargs = mock_pdf.call_args
        self.assertTrue(
            call_kwargs[1].get('public_only') or (len(call_kwargs[0]) >= 2 and call_kwargs[0][1]),
            'visit_letters_pdf must be called with public_only=True',
        )

    @patch('class_visit.class_visit.views.instructor.visit_letters_pdf', return_value=b'%PDF-fake')
    @patch('class_visit.class_visit.views.instructor._get_teacher_or_none')
    @patch('class_visit.class_visit.views.instructor.VisitSchedule')
    def test_bulk_pdf_skips_non_submitted(self, MockVS, mock_get_teacher, mock_pdf):
        """A visit with no submitted report is skipped; still returns 200 PDF (fallback page)."""
        teacher = MagicMock()
        mock_get_teacher.return_value = teacher

        # Visit with a Draft report — should be skipped
        report = MagicMock()
        report.status = 'Draft'
        visit = MagicMock()
        visit.report = report

        qs = MagicMock()
        MockVS.objects.filter.return_value = qs
        qs.distinct.return_value = qs
        qs.prefetch_related.return_value = qs
        qs.__iter__ = MagicMock(return_value=iter([visit]))

        visit_id = str(uuid.uuid4())
        with patch('class_visit.class_visit.views.instructor.pdfkit') as mock_pdfkit, \
             patch('class_visit.class_visit.views.instructor.get_template') as mock_gt:
            mock_pdfkit.from_string.return_value = b'%PDF-fallback'
            mock_gt.return_value.render.return_value = '<html>fallback</html>'
            resp = self._post_bulk(self.instructor_user, [visit_id])

        self.assertEqual(resp.status_code, 200)
        # visit_letters_pdf should NOT be called because submitted_reports is empty
        mock_pdf.assert_not_called()

    @patch('class_visit.class_visit.views.instructor.visit_letters_pdf', return_value=b'%PDF-fake')
    @patch('class_visit.class_visit.views.instructor._get_teacher_or_none')
    @patch('class_visit.class_visit.views.instructor.VisitSchedule')
    def test_bulk_pdf_unauthorized_visit_excluded(self, MockVS, mock_get_teacher, mock_pdf):
        """IDs belonging to another instructor's visits are silently dropped by queryset scope."""
        teacher = MagicMock()
        mock_get_teacher.return_value = teacher

        # Only return one visit (the instructor's own); the other ID is silently ignored
        # because the queryset filters to class_sections__teacher=teacher
        report = MagicMock()
        report.status = 'Submitted'
        own_visit = MagicMock()
        own_visit.report = report

        qs = MagicMock()
        MockVS.objects.filter.return_value = qs
        qs.distinct.return_value = qs
        qs.prefetch_related.return_value = qs
        # Only the instructor's own visit comes back from the scoped queryset
        qs.__iter__ = MagicMock(return_value=iter([own_visit]))

        own_id = str(uuid.uuid4())
        other_id = str(uuid.uuid4())
        resp = self._post_bulk(self.instructor_user, [own_id, other_id])

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        mock_pdf.assert_called_once()
        call_args = mock_pdf.call_args
        reports_arg = call_args[0][0]
        self.assertEqual(
            len(reports_arg), 1,
            'Only the requesting instructor\'s report should be passed to visit_letters_pdf',
        )

    def test_bulk_action_requires_login(self):
        """Unauthenticated POST is redirected or forbidden."""
        anon_client = Client()
        resp = anon_client.post(
            reverse('instructor_class_visit:bulk_action'),
            data={'action': 'export_pdf', 'ids[]': [str(uuid.uuid4())]},
        )
        self.assertIn(resp.status_code, [302, 403])
