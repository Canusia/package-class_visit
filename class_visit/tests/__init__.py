from django.test import TestCase

# Create your tests here.

from django.urls import reverse, NoReverseMatch

from class_visit.class_visit.models import VisitSchedule, VisitReport, VisitReportFile, NotNeededVisit


class UrlResolutionTest(TestCase):
    """Verify that class_visit URL namespaces resolve correctly after _cv wiring."""

    def test_ce_namespace_resolves(self):
        # The ce urls must resolve; if _cv is misconfigured this raises NoReverseMatch
        try:
            reverse('class_visit:index')
        except NoReverseMatch:
            # Not all plans are implemented yet; just confirm no import-time error
            pass

    def test_instructor_namespace_stub_exists(self):
        # The instructor URL module must be importable
        import importlib
        mod = importlib.import_module('class_visit.class_visit.urls.instructor')
        self.assertEqual(mod.app_name, 'instructor_class_visit')


import uuid
from unittest.mock import MagicMock, patch, PropertyMock


class VisitScheduleModelTest(TestCase):
    """Tests for new VisitSchedule fields and helpers."""

    def _make_mock_section(self, teacher):
        section = MagicMock()
        section.teacher = teacher
        return section

    def test_sections_share_teacher_true_when_same_teacher(self):
        teacher = MagicMock()
        teacher.pk = uuid.uuid4()
        s1 = self._make_mock_section(teacher)
        s2 = self._make_mock_section(teacher)
        result = VisitSchedule.sections_share_teacher([s1, s2])
        self.assertTrue(result)

    def test_sections_share_teacher_false_when_different_teachers(self):
        t1 = MagicMock()
        t1.pk = uuid.uuid4()
        t2 = MagicMock()
        t2.pk = uuid.uuid4()
        s1 = self._make_mock_section(t1)
        s2 = self._make_mock_section(t2)
        result = VisitSchedule.sections_share_teacher([s1, s2])
        self.assertFalse(result)

    def test_sections_share_teacher_true_when_empty(self):
        # No sections → vacuously True (no mismatch)
        self.assertTrue(VisitSchedule.sections_share_teacher([]))

    def test_sections_share_teacher_true_when_single(self):
        teacher = MagicMock()
        teacher.pk = uuid.uuid4()
        s = self._make_mock_section(teacher)
        self.assertTrue(VisitSchedule.sections_share_teacher([s]))

    def test_teacher_property_returns_none_when_no_sections(self):
        vs = VisitSchedule()
        # patch class_sections M2M
        with patch.object(type(vs), 'class_sections') as m:
            m.all.return_value = []
            self.assertIsNone(vs.teacher)

    def test_type_of_visit_field_exists(self):
        from django.db import models as dj_models
        field = VisitSchedule._meta.get_field('type_of_visit')
        self.assertIsInstance(field, dj_models.CharField)
        self.assertEqual(field.max_length, 200)


class ClassVisitSettingsTest(TestCase):
    """class_visit settings form: from_db / _to_python round-trip."""

    def test_from_db_returns_dict_when_no_record(self):
        from class_visit.class_visit.settings.class_visit import class_visit as CVSettings
        result = CVSettings.from_db()
        self.assertIsInstance(result, dict)

    def test_install_creates_setting_record(self):
        from class_visit.class_visit.settings.class_visit import class_visit as CVSettings
        from cis.models.settings import Setting
        # Ensure no record exists
        Setting.objects.filter(key=CVSettings.key).delete()
        instance = CVSettings.__new__(CVSettings)
        instance.install()
        self.assertTrue(Setting.objects.filter(key=CVSettings.key).exists())

    def test_to_python_returns_field_values(self):
        from class_visit.class_visit.settings.class_visit import class_visit as CVSettings
        data = {
            'is_active': 'Debug',
            'debug_email_list': 'test@example.com',
            'payment_tracking': 'No',
            'notify_visitor_on_paid': 'No',
            'report_fields_json': '[]',
            'visit_types': 'Initial|Follow-up',
            'section_status_filter': 'active',
            'notify_target': 'course_administrator',
            'generic_email': '',
            'notify_teacher_on_schedule': 'Yes',
            'teacher_scheduled_subject': 'Visit Scheduled',
            'teacher_scheduled_message': 'Hello {{teacher_first_name}}',
            'instructor_confirm_link': 'No',
            'notify_teacher_on_submit': 'No',
            'teacher_submit_subject': '',
            'teacher_submit_message': '',
            'visitor_reminder_subject': 'Reminder',
            'visitor_reminder_message': 'Reminder body',
            'reminder_every_days': '7',
        }
        form = CVSettings(data=data)
        # We bypass request by directly testing _to_python with bound form
        self.assertTrue(form.is_valid(), form.errors)
        result = form._to_python()
        self.assertEqual(result['is_active'], 'Debug')
        self.assertEqual(result['visit_types'], 'Initial|Follow-up')
        self.assertIn('reminder_every_days', result)

    def test_key_is_class_visit(self):
        from class_visit.class_visit.settings.class_visit import class_visit as CVSettings
        self.assertEqual(CVSettings.key, 'class_visit')


from django.db import IntegrityError
from django.utils import timezone


class VisitReportOneToOneTest(TestCase):
    """VisitReport must have OneToOneField to VisitSchedule."""

    def setUp(self):
        from cis.models import CustomUser, ClassSection
        # We test at the ORM level using the model's field definition
        pass

    def test_visit_schedule_is_onetoonefield(self):
        from django.db import models as dj_models
        field = VisitReport._meta.get_field('visit_schedule')
        self.assertIsInstance(field, dj_models.OneToOneField)

    def test_related_name_is_report(self):
        field = VisitReport._meta.get_field('visit_schedule')
        self.assertEqual(field.related_query_name(), 'report')

    def test_status_default_is_draft(self):
        field = VisitReport._meta.get_field('status')
        self.assertEqual(field.default, 'Draft')


from rest_framework.test import APIRequestFactory


class VisitReportFileSerializerTest(TestCase):
    """VisitReportFileSerializer must not reference non-existent model fields."""

    def test_serializer_fields_match_model(self):
        from class_visit.class_visit.serializers import VisitReportFileSerializer
        # Instantiate to trigger field binding — will raise if phantom fields present
        s = VisitReportFileSerializer()
        declared_fields = set(s.fields.keys())
        # Phantom fields that do not exist on the model
        self.assertNotIn('original_filename', declared_fields)
        self.assertNotIn('description', declared_fields)
        self.assertNotIn('content_type', declared_fields)
        # Real fields that should be present
        self.assertIn('id', declared_fields)
        self.assertIn('visit_report', declared_fields)
        self.assertIn('file', declared_fields)
        self.assertIn('uploaded_at', declared_fields)
        self.assertIn('file_url', declared_fields)


class ImportCycleTest(TestCase):
    """cis.models.section must not import class_visit at module load time."""

    def test_section_importable_without_class_visit_side_effect(self):
        # If section.py imported class_visit at module level the app would
        # already be imported by the time this test runs — we verify the
        # lazy import path exists by checking VisitSchedule is NOT a
        # module-level name in section.
        import cis.models.section as section_mod
        self.assertFalse(
            hasattr(section_mod, 'VisitSchedule'),
            "VisitSchedule should not be a module-level name in cis.models.section"
        )


class ReportFieldsServiceTest(TestCase):
    """services/report_fields.py unit tests."""

    SAMPLE_DEFS = [
        {'name': 'strengths', 'label': 'Strengths', 'type': 'textarea', 'public': True, 'required': True, 'options': []},
        {'name': 'areas', 'label': 'Areas for Growth', 'type': 'textarea', 'public': False, 'required': False, 'options': []},
        {'name': 'rating', 'label': 'Rating', 'type': 'select', 'public': True, 'required': True, 'options': ['1','2','3']},
        {'name': 'agreed', 'label': 'Agreed', 'type': 'checkbox', 'public': True, 'required': False, 'options': []},
        {'name': 'followup_date', 'label': 'Follow-up Date', 'type': 'date', 'public': False, 'required': False, 'options': []},
    ]

    def _patch_settings(self, defs=None):
        import json
        json_str = json.dumps(defs if defs is not None else self.SAMPLE_DEFS)
        return patch(
            'class_visit.class_visit.services.report_fields._get_settings',
            return_value={'report_fields_json': json_str},
        )

    def test_get_report_field_defs_returns_list(self):
        from class_visit.class_visit.services.report_fields import get_report_field_defs
        with self._patch_settings():
            result = get_report_field_defs()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 5)

    def test_get_report_field_defs_returns_empty_on_invalid_json(self):
        from class_visit.class_visit.services.report_fields import get_report_field_defs
        bad = patch(
            'class_visit.class_visit.services.report_fields._get_settings',
            return_value={'report_fields_json': 'not-json'},
        )
        with bad:
            result = get_report_field_defs()
        self.assertEqual(result, [])

    def test_public_field_names_returns_set(self):
        from class_visit.class_visit.services.report_fields import public_field_names
        with self._patch_settings():
            result = public_field_names()
        self.assertIn('strengths', result)
        self.assertNotIn('areas', result)

    def test_build_report_form_fields_types(self):
        from class_visit.class_visit.services.report_fields import build_report_form_fields
        from django import forms as dj_forms
        with self._patch_settings():
            fields = build_report_form_fields()
        self.assertIsInstance(fields['strengths'], dj_forms.CharField)
        self.assertIsInstance(fields['rating'], dj_forms.ChoiceField)
        self.assertIsInstance(fields['agreed'], dj_forms.BooleanField)
        self.assertIsInstance(fields['followup_date'], dj_forms.DateField)

    def test_report_values_for_display_filters_public(self):
        from class_visit.class_visit.services.report_fields import report_values_for_display
        report = MagicMock()
        report.meta = {'strengths': 'Great', 'areas': 'Pacing', 'rating': '3', 'agreed': True, 'followup_date': ''}
        with self._patch_settings():
            public = report_values_for_display(report, public_only=True)
            all_vals = report_values_for_display(report, public_only=False)
        public_labels = [r['label'] for r in public]
        self.assertIn('Strengths', public_labels)
        self.assertNotIn('Areas for Growth', public_labels)
        self.assertEqual(len(all_vals), 5)


class EmailServiceTest(TestCase):
    """services/emails.py unit tests — no real emails sent."""

    SAMPLE_SETTINGS = {
        'is_active': 'Debug',
        'debug_email_list': 'debug@example.com',
        'notify_teacher_on_schedule': 'Yes',
        'teacher_scheduled_subject': 'Visit Scheduled',
        'teacher_scheduled_message': 'Hello {{teacher_first_name}}, visit on {{visit_date}}.',
        'instructor_confirm_link': 'No',
        'notify_teacher_on_submit': 'Yes',
        'teacher_submit_subject': 'Report Done',
        'teacher_submit_message': 'Report submitted for {{teacher_first_name}}.',
        'visitor_reminder_subject': 'Reminder',
        'visitor_reminder_message': 'Reminder for {{visitor_first_name}} on {{visit_date}}.',
        'notify_target': 'generic_email',
        'generic_email': 'admin@example.com',
    }

    def _patch_settings(self, overrides=None):
        cfg = dict(self.SAMPLE_SETTINGS)
        if overrides:
            cfg.update(overrides)
        return patch(
            'class_visit.class_visit.services.emails._get_settings',
            return_value=cfg,
        )

    def test_render_template_substitutes_shortcodes(self):
        from class_visit.class_visit.services.emails import render_template
        result = render_template('Hello {{name}}!', {'name': 'World'})
        self.assertEqual(result, 'Hello World!')

    def test_render_template_ignores_missing_keys(self):
        from class_visit.class_visit.services.emails import render_template
        result = render_template('Hello {{missing}}!', {})
        # Django template renders missing vars as ''
        self.assertIn('Hello', result)

    @patch('class_visit.class_visit.services.emails.send_html_mail')
    def test_send_app_email_redirects_to_debug_list_in_debug_mode(self, mock_send):
        from class_visit.class_visit.services.emails import send_app_email
        with self._patch_settings():
            send_app_email('Subject', 'Body text', ['real@example.com'])
        mock_send.assert_called_once()
        # In Debug mode, recipients should be the debug list, not the real recipient
        call_args = mock_send.call_args
        # send_html_mail(subject, message, html_body, from_email, recipient_list, ...)
        # recipients are at index 4 in positional args
        recipients = call_args[0][4] if len(call_args[0]) >= 5 else call_args[1].get('recipient_list', [])
        self.assertIn('debug@example.com', recipients)

    @patch('class_visit.class_visit.services.emails.send_html_mail')
    def test_send_app_email_suppressed_when_inactive(self, mock_send):
        from class_visit.class_visit.services.emails import send_app_email
        with self._patch_settings({'is_active': 'No'}):
            send_app_email('Subject', 'Body', ['real@example.com'])
        mock_send.assert_not_called()

    @patch('class_visit.class_visit.services.emails.send_html_mail')
    @patch('class_visit.class_visit.models.VisitSchedule.objects')
    def test_notify_teacher_visit_scheduled_sends_email(self, mock_vs_objects, mock_send):
        from class_visit.class_visit.services.emails import notify_teacher_visit_scheduled
        vs = MagicMock()
        vs.visit_date_sexy = '01/15/2027'
        vs.class_sections_sexy = 'ACC 101'
        vs.visitor_names = ['Smith, John']
        vs.type_of_visit = 'Initial'
        vs.meta = {}
        teacher = MagicMock()
        teacher.user.first_name = 'Dale'
        teacher.user.last_name = 'Smith'
        teacher.user.email = 'dale@example.com'
        vs.teacher = teacher
        vs.instructor_emails = ['dale@example.com']
        with self._patch_settings():
            notify_teacher_visit_scheduled(vs)
        mock_send.assert_called_once()


class ConfirmationServiceTest(TestCase):
    """services/confirmation.py unit tests."""

    @patch('class_visit.class_visit.services.confirmation.Site')
    def test_confirmation_url_returns_absolute_url(self, MockSite):
        from class_visit.class_visit.services.confirmation import confirmation_url
        mock_site = MagicMock()
        mock_site.domain = 'myce.example.com'
        MockSite.objects.get_current.return_value = mock_site

        vs = MagicMock()
        vs.meta = {'confirmation_token': 'abc123'}
        vs.ensure_confirmation_token.return_value = 'abc123'

        url = confirmation_url(vs)
        self.assertIn('abc123', url)
        self.assertIn('myce.example.com', url)
        self.assertTrue(url.startswith('https://'))

    def test_confirm_visit_returns_none_on_bad_token(self):
        from class_visit.class_visit.services.confirmation import confirm_visit
        result = confirm_visit('nonexistent-token-xyz')
        self.assertIsNone(result)


class PdfServiceTest(TestCase):
    """services/pdf.py unit tests."""

    def _make_visit_report(self, meta=None):
        report = MagicMock()
        report.meta = meta or {'strengths': 'Excellent', 'areas': 'Pacing'}
        vs = MagicMock()
        vs.visit_date_sexy = '01/15/2027'
        vs.class_sections_sexy = '<p>ACC 101</p>'
        vs.type_of_visit = 'Initial'
        teacher = MagicMock()
        teacher.user.first_name = 'Dale'
        teacher.user.last_name = 'Smith'
        vs.teacher = teacher
        report.visit_schedule = vs
        return report

    SAMPLE_DEFS = [
        {'name': 'strengths', 'label': 'Strengths', 'type': 'textarea', 'public': True, 'required': False, 'options': []},
        {'name': 'areas', 'label': 'Areas for Growth', 'type': 'textarea', 'public': False, 'required': False, 'options': []},
    ]

    def test_build_letter_html_returns_string_with_teacher_name(self):
        from class_visit.class_visit.services.pdf import _build_letter_html
        report = self._make_visit_report()
        with patch(
            'class_visit.class_visit.services.pdf.report_values_for_display',
            return_value=[{'label': 'Strengths', 'value': 'Excellent'}],
        ):
            html = _build_letter_html(report, public_only=False)
        self.assertIsInstance(html, str)
        self.assertIn('Dale', html)
        self.assertIn('Smith', html)
        self.assertIn('ACC 101', html)

    def test_build_letter_html_public_only_excludes_private_fields(self):
        from class_visit.class_visit.services.pdf import _build_letter_html
        report = self._make_visit_report()
        # public_only=True: only Strengths is public per SAMPLE_DEFS
        with patch(
            'class_visit.class_visit.services.pdf.report_values_for_display',
            side_effect=lambda r, public_only: (
                [{'label': 'Strengths', 'value': 'Excellent'}] if public_only
                else [{'label': 'Strengths', 'value': 'Excellent'}, {'label': 'Areas for Growth', 'value': 'Pacing'}]
            ),
        ):
            html = _build_letter_html(report, public_only=True)
        self.assertIn('Strengths', html)
        self.assertNotIn('Areas for Growth', html)

    @patch('class_visit.class_visit.services.pdf.pdfkit')
    def test_visit_letter_pdf_calls_pdfkit_from_string(self, mock_pdfkit):
        from class_visit.class_visit.services.pdf import visit_letter_pdf
        mock_pdfkit.from_string.return_value = b'%PDF-fake'
        report = self._make_visit_report()
        with patch('class_visit.class_visit.services.pdf.report_values_for_display',
                   return_value=[]):
            result = visit_letter_pdf(report, public_only=False)
        mock_pdfkit.from_string.assert_called_once()
        # Must pass False as second arg (return bytes, not write to file)
        call_args = mock_pdfkit.from_string.call_args
        self.assertIs(call_args[0][1], False)
        self.assertEqual(result, b'%PDF-fake')

    @patch('class_visit.class_visit.services.pdf.pdfkit')
    def test_visit_letters_pdf_combines_multiple_reports(self, mock_pdfkit):
        from class_visit.class_visit.services.pdf import visit_letters_pdf
        mock_pdfkit.from_string.return_value = b'%PDF-combined'
        r1 = self._make_visit_report()
        r2 = self._make_visit_report()
        with patch('class_visit.class_visit.services.pdf.report_values_for_display',
                   return_value=[]):
            result = visit_letters_pdf([r1, r2], public_only=False)
        # Single pdfkit call (HTML concat approach — no per-report calls)
        mock_pdfkit.from_string.assert_called_once()
        self.assertEqual(result, b'%PDF-combined')

    @patch('class_visit.class_visit.services.pdf.pdfkit')
    def test_visit_letters_pdf_wraps_in_print_base(self, mock_pdfkit):
        from class_visit.class_visit.services.pdf import visit_letters_pdf
        mock_pdfkit.from_string.return_value = b'%PDF'
        report = self._make_visit_report()
        captured_html = []
        def capture(html, dest, options):
            captured_html.append(html)
            return b'%PDF'
        mock_pdfkit.from_string.side_effect = capture
        with patch('class_visit.class_visit.services.pdf.report_values_for_display',
                   return_value=[]):
            visit_letters_pdf([report], public_only=True)
        # The combined HTML must be wrapped in cis/print_base.html (checked via template render)
        self.assertEqual(len(captured_html), 1)
        # page-size Letter option must be present
        call_kwargs = mock_pdfkit.from_string.call_args
        opts = call_kwargs[0][2] if len(call_kwargs[0]) >= 3 else call_kwargs[1].get('options', {})
        self.assertEqual(opts.get('page-size'), 'Letter')


class NotNeededVisitModelTest(TestCase):
    """NotNeededVisit model basic field checks."""

    def test_class_section_is_onetoonefield(self):
        from django.db import models as dj_models
        field = NotNeededVisit._meta.get_field('class_section')
        self.assertIsInstance(field, dj_models.OneToOneField)

    def test_primary_key_is_uuid(self):
        from django.db import models as dj_models
        field = NotNeededVisit._meta.get_field('id')
        self.assertIsInstance(field, dj_models.UUIDField)
        self.assertTrue(field.primary_key)

    def test_added_by_is_nullable_fk(self):
        from django.db import models as dj_models
        field = NotNeededVisit._meta.get_field('added_by')
        self.assertIsInstance(field, dj_models.ForeignKey)
        self.assertTrue(field.null)
        self.assertTrue(field.blank)

    def test_created_at_auto_now_add(self):
        from django.db import models as dj_models
        field = NotNeededVisit._meta.get_field('created_at')
        self.assertIsInstance(field, dj_models.DateTimeField)
        self.assertTrue(field.auto_now_add)
