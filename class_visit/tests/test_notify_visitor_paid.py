from unittest.mock import patch, MagicMock

from django.test import TestCase

from class_visit.class_visit.services import emails


def _report(first='Ann', email='ann@x.com'):
    visitor = MagicMock(first_name=first, email=email)
    vs = MagicMock()
    vs.visitors.all.return_value = [visitor]
    vs.visit_date_sexy = '06/01/2026'
    vs.class_sections_sexy = 'CHEM 101'
    report = MagicMock()
    report.visit_schedule = vs
    return report


class NotifyVisitorPaidTests(TestCase):

    @patch('class_visit.class_visit.services.emails.send_app_email')
    @patch('class_visit.class_visit.services.emails._get_settings')
    def test_sends_when_enabled_and_renders_shortcodes(self, mock_settings, mock_send):
        mock_settings.return_value = {
            'payment_tracking': 'Yes',
            'notify_visitor_on_paid': 'Yes',
            'visitor_paid_subject': 'Paid',
            'visitor_paid_message': 'Hi {{visitor_first_name}} for {{class_sections}}',
        }
        emails.notify_visitor_payment_processed(_report())
        mock_send.assert_called_once()
        subject, message, recipients = mock_send.call_args[0]
        self.assertEqual(subject, 'Paid')
        self.assertIn('Hi Ann for CHEM 101', message)   # shortcodes rendered
        self.assertEqual(recipients, ['ann@x.com'])

    @patch('class_visit.class_visit.services.emails.send_app_email')
    @patch('class_visit.class_visit.services.emails._get_settings')
    def test_skips_when_notify_off(self, mock_settings, mock_send):
        mock_settings.return_value = {'payment_tracking': 'Yes', 'notify_visitor_on_paid': 'No'}
        emails.notify_visitor_payment_processed(_report())
        mock_send.assert_not_called()

    @patch('class_visit.class_visit.services.emails.send_app_email')
    @patch('class_visit.class_visit.services.emails._get_settings')
    def test_skips_when_payment_tracking_off(self, mock_settings, mock_send):
        mock_settings.return_value = {'payment_tracking': 'No', 'notify_visitor_on_paid': 'Yes'}
        emails.notify_visitor_payment_processed(_report())
        mock_send.assert_not_called()
