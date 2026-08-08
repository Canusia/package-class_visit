"""
Regression tests for HTML-returning model properties and the email body pipeline.

Bug: `class_sections_sexy` (and its siblings) returned a plain `str` containing
markup. `services.emails.render_template()` renders the settings body with
`Template(text).render(Context(ctx))`, which autoescapes — so `{{class_sections}}`
reached recipients as `&lt;p&gt;…&lt;br&gt;` and the email read as plain text.

The fix returns SafeString from those properties via `format_html`, which escapes
the interpolated DB values but keeps the markup intact.
"""
from unittest.mock import MagicMock, PropertyMock, patch

from django.test import TestCase
from django.utils.safestring import SafeString

from ..models import VisitReport, VisitSchedule


def _section(course='ACC 101', class_number='1234', section_number='01',
             period_time='9:00 AM', highschool='Central HS',
             teacher_name='Smith, Dale', teacher_email='dale@example.com'):
    section = MagicMock()
    section.course = course
    section.class_number = class_number
    section.section_number = section_number
    section.period_time = period_time
    section.highschool = highschool
    section.teacher.__str__ = lambda self: teacher_name
    section.teacher.user.email = teacher_email
    return section


def _visit_with_sections(*sections):
    visit = VisitSchedule()
    patcher = patch.object(VisitSchedule, 'class_sections', new_callable=PropertyMock)
    mock_rel = patcher.start()
    mock_rel.return_value.all.return_value = list(sections)
    return visit, patcher


class SexyPropertiesReturnSafeHtmlTest(TestCase):
    """The _sexy properties must return SafeString so templates don't escape them."""

    def test_class_sections_sexy_is_safe_and_keeps_markup(self):
        visit, patcher = _visit_with_sections(_section())
        try:
            result = visit.class_sections_sexy
        finally:
            patcher.stop()

        self.assertIsInstance(result, SafeString)
        self.assertIn('<p>', result)
        self.assertIn('<br>', result)
        self.assertIn('ACC 101 (1234/01)', result)
        self.assertNotIn('&lt;p&gt;', result)

    def test_class_sections_sexy_concatenates_every_section(self):
        visit, patcher = _visit_with_sections(
            _section(course='ACC 101'),
            _section(course='BIO 202'),
        )
        try:
            result = visit.class_sections_sexy
        finally:
            patcher.stop()

        self.assertIn('ACC 101', result)
        self.assertIn('BIO 202', result)
        self.assertEqual(result.count('<p>'), 2)

    def test_class_sections_sexy_escapes_interpolated_data(self):
        """Markup is trusted; the DB values dropped into it are not."""
        visit, patcher = _visit_with_sections(_section(course='<script>alert(1)</script>'))
        try:
            result = visit.class_sections_sexy
        finally:
            patcher.stop()

        self.assertNotIn('<script>', result)
        self.assertIn('&lt;script&gt;', result)

    def test_class_sections_sexy_empty_when_no_sections(self):
        visit, patcher = _visit_with_sections()
        try:
            result = visit.class_sections_sexy
        finally:
            patcher.stop()

        self.assertEqual(result, '')
        self.assertIsInstance(result, SafeString)

    def test_instructor_sexy_is_safe(self):
        visit, patcher = _visit_with_sections(_section())
        try:
            result = visit.instructor_sexy
        finally:
            patcher.stop()

        self.assertIsInstance(result, SafeString)
        self.assertIn('dale@example.com', result)
        self.assertNotIn('&lt;p&gt;', result)

    def test_highschool_sexy_is_safe(self):
        visit, patcher = _visit_with_sections(_section())
        try:
            result = visit.highschool_sexy
        finally:
            patcher.stop()

        self.assertIsInstance(result, SafeString)
        self.assertIn('Central HS', result)
        self.assertNotIn('&lt;p&gt;', result)

    def test_visitors_sexy_is_safe(self):
        visit = VisitSchedule()
        visitor = MagicMock()
        visitor.first_name = 'John'
        visitor.last_name = 'Smith'
        with patch.object(VisitSchedule, 'visitors', new_callable=PropertyMock) as mock_rel:
            mock_rel.return_value.all.return_value = [visitor, visitor]
            result = visit.visitors_sexy

        self.assertIsInstance(result, SafeString)
        self.assertIn('<br>', result)
        self.assertNotIn('&lt;br&gt;', result)

    def test_visit_files_html_is_safe(self):
        report = VisitReport()
        uploaded = MagicMock()
        uploaded.file.name = 'observation.pdf'
        with patch.object(VisitReport, 'files', new_callable=PropertyMock) as mock_rel:
            mock_rel.return_value.all.return_value = [uploaded]
            with patch('cis.utils.get_s3_url', return_value='https://example.com/observation.pdf'):
                result = report.visit_files_html

        self.assertIsInstance(result, SafeString)
        self.assertIn('<a href=', result)
        self.assertNotIn('&lt;a', result)


class EmailBodyRenderingTest(TestCase):
    """End-to-end: the shortcode value survives into the sent HTML body unescaped."""

    CFG = {
        'is_active': 'Yes',
        'debug_email_list': '',
        'visitor_reminder_subject': 'Reminder',
        'visitor_reminder_message': 'Sections: {{class_sections}} / Name: {{visitor_first_name}}',
    }

    def _patch_settings(self, overrides=None):
        cfg = dict(self.CFG)
        cfg.update(overrides or {})
        return patch(
            'class_visit.class_visit.services.emails._get_settings',
            return_value=cfg,
        )

    def _visit_schedule_mock(self, sections_html):
        visitor = MagicMock()
        visitor.first_name = 'John'
        visitor.email = 'john@example.com'

        vs = MagicMock()
        vs.visit_date_sexy = '01/15/2027'
        vs.class_sections_sexy = sections_html
        vs.visitors.all.return_value = [visitor]
        vs.meta = {}
        return vs

    @patch('class_visit.class_visit.models.VisitSchedule.objects')
    @patch('class_visit.class_visit.services.emails.send_html_mail')
    def test_reminder_body_keeps_section_markup(self, mock_send, _mock_objects):
        from django.utils.safestring import mark_safe

        from ..services.emails import remind_visitor_report_pending

        vs = self._visit_schedule_mock(mark_safe('<p>ACC 101</p>'))
        with patch('django.conf.settings.DEBUG', False):
            with self._patch_settings():
                remind_visitor_report_pending(vs)

        mock_send.assert_called_once()
        html_body = mock_send.call_args[0][2]
        self.assertIn('<p>ACC 101</p>', html_body)
        self.assertNotIn('&lt;p&gt;ACC 101', html_body)

    @patch('class_visit.class_visit.models.VisitSchedule.objects')
    @patch('class_visit.class_visit.services.emails.send_html_mail')
    def test_plain_text_alternative_is_stripped_of_markup(self, mock_send, _mock_objects):
        from django.utils.safestring import mark_safe

        from ..services.emails import remind_visitor_report_pending

        vs = self._visit_schedule_mock(mark_safe('<p>ACC 101</p>'))
        with patch('django.conf.settings.DEBUG', False):
            with self._patch_settings():
                remind_visitor_report_pending(vs)

        text_body = mock_send.call_args[0][1]
        self.assertIn('ACC 101', text_body)
        self.assertNotIn('<p>', text_body)

    @patch('class_visit.class_visit.models.VisitSchedule.objects')
    @patch('class_visit.class_visit.services.emails.send_html_mail')
    def test_plain_context_values_are_still_escaped(self, mock_send, _mock_objects):
        """mark_safe must not leak to genuinely plain-text shortcodes."""
        from django.utils.safestring import mark_safe

        from ..services.emails import remind_visitor_report_pending

        vs = self._visit_schedule_mock(mark_safe('<p>ACC 101</p>'))
        vs.visitors.all.return_value[0].first_name = '<script>alert(1)</script>'
        with patch('django.conf.settings.DEBUG', False):
            with self._patch_settings():
                remind_visitor_report_pending(vs)

        html_body = mock_send.call_args[0][2]
        self.assertNotIn('<script>', html_body)
        self.assertIn('&lt;script&gt;', html_body)
