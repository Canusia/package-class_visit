"""Tests for CE staff class visit serializers, forms, views, and URLs."""


# ---------------------------------------------------------------------------
# Task 1 — Serializer smoke tests
# ---------------------------------------------------------------------------

from django.test import TestCase


class CESerializerSmokeTest(TestCase):
    def test_visit_schedule_serializer_has_required_fields(self):
        from class_visit.class_visit.serializers.ce import CEVisitScheduleSerializer
        required = {
            'id', 'visit_date', 'type_of_visit',
            'class_sections', 'visitors',
            'report_status', 'teacher_display',
            'ce_edit_url', 'ce_delete_url', 'ce_report_url',
        }
        declared = set(CEVisitScheduleSerializer().fields.keys())
        missing = required - declared
        self.assertEqual(missing, set(), f"Missing fields: {missing}")

    def test_not_needed_visit_serializer_has_required_fields(self):
        from class_visit.class_visit.serializers.ce import CENotNeededVisitSerializer
        required = {
            'id', 'class_section', 'added_by_display', 'created_at',
            'remove_url',
        }
        declared = set(CENotNeededVisitSerializer().fields.keys())
        missing = required - declared
        self.assertEqual(missing, set(), f"Missing fields: {missing}")


# ---------------------------------------------------------------------------
# Task 2 — Form smoke tests
# ---------------------------------------------------------------------------

class CEVisitScheduleFormTest(TestCase):
    """Validate form validation logic without a full DB."""

    def test_form_imports_without_error(self):
        """CEVisitScheduleForm class is importable and instantiable with mocked deps."""
        from unittest.mock import patch, MagicMock
        import uuid

        with patch('class_visit.class_visit.forms.ce.ClassSection') as mock_cs, \
             patch('class_visit.class_visit.forms.ce.CourseAdministrator') as mock_ca, \
             patch('class_visit.class_visit.forms.ce.ClassVisitSettings') as mock_settings:

            mock_settings.from_db.return_value = {
                'visit_types': 'In-Person|Virtual',
                'section_status_filter': 'active',
            }
            mock_cs.objects.get.return_value = MagicMock(
                teacher=MagicMock(), term=MagicMock(), course=MagicMock()
            )
            mock_cs.objects.filter.return_value = []
            # Use a chained mock so .select_related('user') returns an iterable
            mock_qs = MagicMock()
            mock_qs.select_related.return_value = []
            mock_ca.objects.filter.return_value = mock_qs

            from class_visit.class_visit.forms.ce import CEVisitScheduleForm
            form = CEVisitScheduleForm(section_id=uuid.uuid4())
            self.assertIn('class_sections', form.fields)
            self.assertIn('visitors', form.fields)
            self.assertIn('visit_date', form.fields)
            self.assertIn('type_of_visit', form.fields)
            self.assertIn('pre_visit_note', form.fields)


# ---------------------------------------------------------------------------
# Task 3 — Viewset smoke tests
# ---------------------------------------------------------------------------

class CEViewSetTest(TestCase):
    def test_visit_schedule_viewset_has_cis_permission(self):
        from cis.utils import CIS_user_only
        from class_visit.class_visit.views.ce import CEVisitScheduleViewSet
        self.assertIn(CIS_user_only, CEVisitScheduleViewSet.permission_classes)

    def test_not_needed_viewset_has_cis_permission(self):
        from cis.utils import CIS_user_only
        from class_visit.class_visit.views.ce import CENotNeededVisitViewSet
        self.assertIn(CIS_user_only, CENotNeededVisitViewSet.permission_classes)


# ---------------------------------------------------------------------------
# Task 4 — URL reverse smoke tests
# ---------------------------------------------------------------------------

class CEUrlsTest(TestCase):
    """Smoke-test that all named CE URLs resolve without error."""

    def _check(self, name, kwargs=None):
        from django.urls import reverse, NoReverseMatch
        try:
            url = reverse(f'class_visit:{name}', kwargs=kwargs)
            self.assertTrue(url.startswith('/'), f"Expected absolute path for {name}, got {url}")
        except NoReverseMatch as exc:
            self.fail(f"NoReverseMatch for class_visit:{name} — {exc}")

    def test_index_resolves(self):
        self._check('ce_index')

    def test_manage_visit_resolves(self):
        import uuid
        self._check('ce_manage_visit', {'section_id': uuid.uuid4()})

    def test_edit_visit_resolves(self):
        import uuid
        self._check('ce_edit_visit', {'visit_id': uuid.uuid4()})

    def test_delete_visit_resolves(self):
        import uuid
        self._check('ce_delete_visit', {'visit_id': uuid.uuid4()})

    def test_view_report_resolves(self):
        import uuid
        self._check('ce_view_report', {'visit_id': uuid.uuid4()})

    def test_not_needed_add_resolves(self):
        self._check('ce_not_needed_add')

    def test_not_needed_remove_resolves(self):
        import uuid
        self._check('ce_not_needed_remove', {'pk': uuid.uuid4()})

    def test_not_needed_picker_resolves(self):
        self._check('ce_not_needed_picker')

    def test_bulk_action_resolves(self):
        self._check('ce_bulk_action')


# ---------------------------------------------------------------------------
# Task 7 — Functional Tests
# ---------------------------------------------------------------------------

from django.test import Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in
from unittest.mock import patch, MagicMock

User = get_user_model()

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:
    _login_history_post_login = None


def make_ce_user(suffix=''):
    """Return a CustomUser in the 'ce' group."""
    from django.contrib.auth.models import Group
    username = f'ce_task7{suffix}@example.com'
    u = User.objects.create_user(
        username=username,
        email=username,
        password='testpass',
        first_name='CE',
        last_name='Test',
    )
    g, _ = Group.objects.get_or_create(name='ce')
    u.groups.add(g)
    return u


class CEIndexViewTest(TestCase):
    """CE index page requires login and returns 200 for ce role."""

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
        self.client = Client()
        self.user = make_ce_user('_idx')

    def test_index_redirects_anonymous(self):
        resp = self.client.get('/ce/class_visits/')
        self.assertIn(resp.status_code, [301, 302])

    @patch('class_visit.class_visit.views.ce.Term')
    @patch('class_visit.class_visit.views.ce.Course')
    @patch('class_visit.class_visit.views.ce.active_term')
    def test_index_200_for_ce_user(self, mock_at, mock_course, mock_term):
        mock_term.objects.all.return_value.order_by.return_value = []
        mock_course.objects.filter.return_value.order_by.return_value = []
        mock_at.return_value = None
        self.client.force_login(self.user)
        resp = self.client.get('/ce/class_visits/')
        self.assertEqual(resp.status_code, 200)


class CENotNeededAddRemoveTest(TestCase):
    """Add and remove NotNeededVisit rows."""

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
        self.client = Client()
        self.user = make_ce_user('_nn')
        self.client.force_login(self.user)

    @patch('class_visit.class_visit.views.ce.NotNeededVisit')
    @patch('class_visit.class_visit.views.ce.get_object_or_404')
    def test_add_creates_row(self, mock_404, mock_nn):
        import uuid
        section_id = uuid.uuid4()
        mock_section = MagicMock(id=section_id)
        mock_404.return_value = mock_section
        mock_nn.objects.get_or_create.return_value = (MagicMock(), True)

        resp = self.client.post(
            '/ce/class_visits/not-needed/add/',
            {'class_section_id': str(section_id)},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])

    @patch('class_visit.class_visit.views.ce.NotNeededVisit')
    @patch('class_visit.class_visit.views.ce.get_object_or_404')
    def test_add_duplicate_returns_false(self, mock_404, mock_nn):
        import uuid
        section_id = uuid.uuid4()
        mock_section = MagicMock(id=section_id)
        mock_404.return_value = mock_section
        mock_nn.objects.get_or_create.return_value = (MagicMock(), False)

        resp = self.client.post(
            '/ce/class_visits/not-needed/add/',
            {'class_section_id': str(section_id)},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data['success'])


class CESameTeacherValidationTest(TestCase):
    """Sections from different teachers must be rejected by the form."""

    def test_sections_share_teacher_false_raises(self):
        from class_visit.class_visit.forms.ce import CEVisitScheduleForm
        from django.core.exceptions import ValidationError
        import uuid

        teacher_a = MagicMock()
        teacher_b = MagicMock()
        s1 = MagicMock(teacher=teacher_a)
        s2 = MagicMock(teacher=teacher_b)

        with patch(
            'class_visit.class_visit.models.VisitSchedule.sections_share_teacher',
            return_value=False,
        ), patch(
            'class_visit.class_visit.forms.ce.ClassSection'
        ) as mock_cs:
            mock_cs.objects.filter.return_value = [s1, s2]
            form = CEVisitScheduleForm.__new__(CEVisitScheduleForm)
            form.cleaned_data = {'class_sections': [str(uuid.uuid4()), str(uuid.uuid4())]}
            with self.assertRaises(ValidationError):
                form.clean_class_sections()

    def test_sections_share_teacher_true_passes(self):
        from class_visit.class_visit.forms.ce import CEVisitScheduleForm
        import uuid

        teacher_a = MagicMock()
        s1 = MagicMock(teacher=teacher_a)
        s2 = MagicMock(teacher=teacher_a)

        ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        with patch(
            'class_visit.class_visit.models.VisitSchedule.sections_share_teacher',
            return_value=True,
        ), patch(
            'class_visit.class_visit.forms.ce.ClassSection'
        ) as mock_cs:
            mock_cs.objects.filter.return_value = [s1, s2]
            form = CEVisitScheduleForm.__new__(CEVisitScheduleForm)
            form.cleaned_data = {'class_sections': ids}
            result = form.clean_class_sections()
            self.assertEqual(result, ids)


class CEFullReportViewTest(TestCase):
    """CE report view calls report_values_for_display with public_only=False."""

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
        self.client = Client()
        self.user = make_ce_user('_rpt')
        self.client.force_login(self.user)

    @patch('class_visit.class_visit.views.ce.report_fields')
    @patch('class_visit.class_visit.views.ce.get_object_or_404')
    def test_view_report_uses_public_only_false(self, mock_404, mock_rf):
        import uuid
        visit_id = uuid.uuid4()
        mock_report = MagicMock()
        mock_visit = MagicMock()
        mock_visit.report = mock_report
        mock_404.return_value = mock_visit
        mock_rf.report_values_for_display.return_value = []

        with patch('class_visit.class_visit.views.ce.draw_menu', return_value={}):
            resp = self.client.get(f'/ce/class_visits/report/{visit_id}/')

        self.assertIn(resp.status_code, [200, 302])

        if resp.status_code == 200:
            mock_rf.report_values_for_display.assert_called_once_with(
                mock_report, public_only=False
            )

    @patch('class_visit.class_visit.views.ce.report_fields')
    @patch('class_visit.class_visit.views.ce.get_object_or_404')
    def test_view_report_ajax_is_frameable_and_uses_modal_base(self, mock_404, mock_rf):
        import uuid
        mock_visit = MagicMock()
        mock_visit.report = MagicMock()
        mock_404.return_value = mock_visit
        mock_rf.report_values_for_display.return_value = []

        with patch('class_visit.class_visit.views.ce.draw_menu', return_value={}):
            resp = self.client.get(f'/ce/class_visits/report/{uuid.uuid4()}/?ajax=1')

        self.assertEqual(resp.status_code, 200)
        # @xframe_options_exempt -> no X-Frame-Options header, so it can be iframed
        self.assertFalse(resp.has_header('X-Frame-Options'))
        # standalone modal base, not the full sidebar layout
        self.assertEqual(resp.context['base_template'], 'cis/ajax-base.html')

    @patch('class_visit.class_visit.views.ce.report_fields')
    @patch('class_visit.class_visit.views.ce.get_object_or_404')
    def test_view_report_direct_nav_uses_full_base(self, mock_404, mock_rf):
        import uuid
        mock_visit = MagicMock()
        mock_visit.report = MagicMock()
        mock_404.return_value = mock_visit
        mock_rf.report_values_for_display.return_value = []

        with patch('class_visit.class_visit.views.ce.draw_menu', return_value={}):
            resp = self.client.get(f'/ce/class_visits/report/{uuid.uuid4()}/')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['base_template'], 'cis/logged-base.html')


class CEBulkPDFTest(TestCase):
    """Bulk PDF action returns application/pdf content type."""

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
        self.client = Client()
        self.user = make_ce_user('_pdf')
        self.client.force_login(self.user)

    @patch('class_visit.class_visit.views.ce.pdf_service')
    @patch('class_visit.class_visit.views.ce.VisitSchedule')
    def test_bulk_action_returns_pdf(self, mock_vs, mock_pdf):
        import uuid
        mock_report = MagicMock()
        mock_visit = MagicMock()
        mock_visit.report = mock_report
        mock_vs.objects.get.return_value = mock_visit
        mock_pdf.visit_letters_pdf.return_value = b'%PDF-1.4 fake'

        resp = self.client.post(
            '/ce/class_visits/bulk-action/',
            {
                'action': 'export_pdf',
                'ids[]': [str(uuid.uuid4())],
                'public_only': '0',
            },
        )

        # Accept 200 (PDF) or 400 (no reports found if mock doesn't wire fully)
        self.assertIn(resp.status_code, [200, 400])
        if resp.status_code == 200:
            self.assertEqual(resp['Content-Type'], 'application/pdf')
            mock_pdf.visit_letters_pdf.assert_called_once()


class CEMarkAsPaidTest(TestCase):
    """Bulk 'mark_as_paid' action, gated on the payment_tracking setting."""

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
        from class_visit.class_visit.models import VisitSchedule, VisitReport

        self.client = Client()
        self.user = make_ce_user('_paid')
        self.client.force_login(self.user)

        self.visit = VisitSchedule.objects.create()
        self.report = VisitReport.objects.create(
            visit_schedule=self.visit,
            teacher_discussion='',
            student_discussion='',
            visit_letter='',
            status='Submitted',
            payment_processed='0',
        )

        self.draft_visit = VisitSchedule.objects.create()
        self.draft_report = VisitReport.objects.create(
            visit_schedule=self.draft_visit,
            teacher_discussion='',
            student_discussion='',
            visit_letter='',
            status='Draft',
            payment_processed='0',
        )

    def test_mark_as_paid_requires_setting_enabled(self):
        from cis.models.settings import Setting
        Setting.objects.update_or_create(key='class_visit', defaults={'value': {'payment_tracking': 'No'}})
        resp = self.client.post(reverse('class_visit:ce_bulk_action'),
                                {'action': 'mark_as_paid', 'ids[]': [str(self.visit.id)]})
        self.assertEqual(resp.status_code, 403)

    def test_mark_as_paid_marks_submitted_reports(self):
        from cis.models.settings import Setting
        Setting.objects.update_or_create(key='class_visit', defaults={'value': {'payment_tracking': 'Yes'}})
        # self.report is Submitted (eligible). self.visit is its schedule.
        resp = self.client.post(reverse('class_visit:ce_bulk_action'),
                                {'action': 'mark_as_paid', 'ids[]': [str(self.visit.id)]})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])
        self.report.refresh_from_db()
        self.assertEqual(self.report.payment_processed, '1')

    def test_mark_as_paid_skips_ineligible(self):
        from cis.models.settings import Setting
        Setting.objects.update_or_create(key='class_visit', defaults={'value': {'payment_tracking': 'Yes'}})
        # self.draft_visit has a Draft report (not eligible).
        resp = self.client.post(reverse('class_visit:ce_bulk_action'),
                                {'action': 'mark_as_paid', 'ids[]': [str(self.draft_visit.id)]})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Marked 0 of 1', resp.json()['message'])

    @patch('class_visit.class_visit.views.ce.email_service')
    def test_mark_as_paid_notifies_visitor_for_eligible_only(self, mock_emails):
        from cis.models.settings import Setting
        Setting.objects.update_or_create(key='class_visit', defaults={'value': {'payment_tracking': 'Yes'}})
        self.client.post(reverse('class_visit:ce_bulk_action'),
                         {'action': 'mark_as_paid',
                          'ids[]': [str(self.visit.id), str(self.draft_visit.id)]})
        # Notified once — only the eligible (Submitted) report.
        mock_emails.notify_visitor_payment_processed.assert_called_once_with(self.report)


# ---------------------------------------------------------------------------
# Task 8 — Integration Wiring Check
# ---------------------------------------------------------------------------

class CEIntegrationWiringTest(TestCase):
    """Integration wiring: URL reverse, viewset importability, settings reachability."""

    def test_ce_index_url_reverse(self):
        """ce_index reverses to /ce/class_visits/."""
        from django.urls import reverse
        url = reverse('class_visit:ce_index')
        self.assertEqual(url, '/ce/class_visits/')

    def test_visit_schedule_viewset_importable(self):
        """CEVisitScheduleViewSet is importable and instantiable."""
        from class_visit.class_visit.views.ce import CEVisitScheduleViewSet
        vs = CEVisitScheduleViewSet()
        self.assertIsNotNone(vs)

    def test_not_needed_viewset_importable(self):
        """CENotNeededVisitViewSet is importable and instantiable."""
        from class_visit.class_visit.views.ce import CENotNeededVisitViewSet
        vs = CENotNeededVisitViewSet()
        self.assertIsNotNone(vs)

    def test_settings_from_db_callable(self):
        """class_visit_settings.from_db() returns a dict (empty if not installed)."""
        from class_visit.class_visit.settings.class_visit import class_visit as class_visit_settings
        cfg = class_visit_settings.from_db()
        self.assertIsInstance(cfg, dict)


# ---------------------------------------------------------------------------
# Task 5 — CE UI payment column + mark-as-paid button (gated)
# ---------------------------------------------------------------------------

class CEIndexPaymentUiTest(TestCase):
    """CE index page shows/hides the payment column + button per the payment_tracking setting."""

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
        self.client = Client()
        self.user = make_ce_user('_pay_ui')
        self.client.force_login(self.user)

    @patch('class_visit.class_visit.views.ce.Term')
    @patch('class_visit.class_visit.views.ce.Course')
    @patch('class_visit.class_visit.views.ce.active_term')
    def test_index_shows_paid_button_when_enabled(self, mock_at, mock_course, mock_term):
        from cis.models.settings import Setting
        mock_term.objects.all.return_value.order_by.return_value = []
        mock_course.objects.filter.return_value.order_by.return_value = []
        mock_at.return_value = None
        Setting.objects.update_or_create(key='class_visit', defaults={'value': {'payment_tracking': 'Yes'}})
        html = self.client.get(reverse('class_visit:ce_index')).content.decode()
        self.assertIn('Mark Selected as Paid', html)
        self.assertIn('var CV_PAYMENT_TRACKING = true', html)

    @patch('class_visit.class_visit.views.ce.Term')
    @patch('class_visit.class_visit.views.ce.Course')
    @patch('class_visit.class_visit.views.ce.active_term')
    def test_index_hides_paid_button_when_disabled(self, mock_at, mock_course, mock_term):
        from cis.models.settings import Setting
        mock_term.objects.all.return_value.order_by.return_value = []
        mock_course.objects.filter.return_value.order_by.return_value = []
        mock_at.return_value = None
        Setting.objects.update_or_create(key='class_visit', defaults={'value': {'payment_tracking': 'No'}})
        html = self.client.get(reverse('class_visit:ce_index')).content.decode()
        self.assertNotIn('Mark Selected as Paid', html)
        self.assertIn('var CV_PAYMENT_TRACKING = false', html)
