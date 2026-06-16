"""
Tests for VisitSchedule.send_pending_report_reminders() and _should_remind().

Task 7: classmethod + helper (TDD — failing tests first, then implementation).
"""
import datetime
from unittest.mock import patch, MagicMock

from django.test import TestCase

from class_visit.class_visit.models import _should_remind, VisitSchedule


# ---------------------------------------------------------------------------
# _should_remind unit tests
# ---------------------------------------------------------------------------

class ShouldRemindHelperTests(TestCase):
    """Test the module-level _should_remind(visit, today, reminder_every_days) helper."""

    def _make_visit(self, visit_date_offset_days, meta=None, submitted=False):
        """Return a mock VisitSchedule with the specified attributes."""
        visit = MagicMock(spec=VisitSchedule)
        today = datetime.date.today()
        visit.visit_date = datetime.datetime.combine(
            today + datetime.timedelta(days=visit_date_offset_days),
            datetime.time(9, 0),
        )
        visit.meta = meta or {}
        visit.has_report = MagicMock(return_value=False)
        if submitted:
            mock_report = MagicMock()
            mock_report.status = 'Submitted'
            visit.has_report = MagicMock(return_value=mock_report)
        return visit

    def test_never_sent_and_past_visit_returns_true(self):
        """No reminder_last_sent_on in meta and visit is past → should remind."""
        visit = self._make_visit(visit_date_offset_days=-3, meta={})
        today = datetime.date.today()
        self.assertTrue(_should_remind(visit, today, reminder_every_days=7))

    def test_sent_recently_returns_false(self):
        """Reminder sent 2 days ago with a 7-day window → should NOT remind."""
        two_days_ago = (datetime.date.today() - datetime.timedelta(days=2)).strftime('%m/%d/%Y')
        visit = self._make_visit(
            visit_date_offset_days=-10,
            meta={'reminder_last_sent_on': two_days_ago},
        )
        today = datetime.date.today()
        self.assertFalse(_should_remind(visit, today, reminder_every_days=7))

    def test_sent_exactly_at_window_returns_true(self):
        """Reminder sent exactly N days ago → should remind (boundary inclusive)."""
        seven_days_ago = (datetime.date.today() - datetime.timedelta(days=7)).strftime('%m/%d/%Y')
        visit = self._make_visit(
            visit_date_offset_days=-14,
            meta={'reminder_last_sent_on': seven_days_ago},
        )
        today = datetime.date.today()
        self.assertTrue(_should_remind(visit, today, reminder_every_days=7))

    def test_submitted_report_returns_false(self):
        """Visit with a Submitted report → should NOT remind."""
        visit = self._make_visit(visit_date_offset_days=-5, submitted=True)
        today = datetime.date.today()
        self.assertFalse(_should_remind(visit, today, reminder_every_days=7))

    def test_future_visit_returns_false(self):
        """Visit date is in the future → should NOT remind."""
        visit = self._make_visit(visit_date_offset_days=3, meta={})
        today = datetime.date.today()
        self.assertFalse(_should_remind(visit, today, reminder_every_days=7))

    def test_none_reminder_every_days_defaults_to_never_resend(self):
        """reminder_every_days=None (not configured) and never sent → still remind."""
        visit = self._make_visit(visit_date_offset_days=-5, meta={})
        today = datetime.date.today()
        # None means: always remind if never sent (treat as 0 days threshold)
        self.assertTrue(_should_remind(visit, today, reminder_every_days=None))

    def test_zero_reminder_every_days_resends_every_time(self):
        """reminder_every_days=0 → remind even if sent today."""
        today_str = datetime.date.today().strftime('%m/%d/%Y')
        visit = self._make_visit(
            visit_date_offset_days=-5,
            meta={'reminder_last_sent_on': today_str},
        )
        today = datetime.date.today()
        self.assertTrue(_should_remind(visit, today, reminder_every_days=0))


# ---------------------------------------------------------------------------
# send_pending_report_reminders integration-style tests
# ---------------------------------------------------------------------------

class SendPendingReportRemindersTests(TestCase):
    """Integration-style tests for VisitSchedule.send_pending_report_reminders()."""

    SETTINGS_PATH = 'class_visit.class_visit.models._get_cv_settings'
    EMAIL_PATH = 'class_visit.class_visit.models._remind_visitor_report_pending'

    def _patch_settings(self, is_active='Yes', reminder_every_days=7):
        return patch(self.SETTINGS_PATH, return_value={
            'is_active': is_active,
            'debug_email_list': 'debug@example.com',
            'visitor_reminder_subject': 'Reminder',
            'visitor_reminder_message': 'Please submit your report.',
            'reminder_every_days': reminder_every_days,
        })

    def test_is_active_no_skips_all(self):
        """When is_active=No, classmethod returns early with no emails sent."""
        with self._patch_settings(is_active='No') as mock_cfg, \
                patch(self.EMAIL_PATH) as mock_email:
            summary, log = VisitSchedule.send_pending_report_reminders()
        mock_email.assert_not_called()
        self.assertIn('inactive', summary.lower())

    def test_eligible_visit_triggers_reminder(self):
        """Past visit without a submitted report and not recently reminded → email sent."""
        today = datetime.date.today()
        past_date = datetime.datetime.combine(
            today - datetime.timedelta(days=10),
            datetime.time(9, 0),
        )

        mock_visit = MagicMock(spec=VisitSchedule)
        mock_visit.pk = 'test-pk-1'
        mock_visit.visit_date = past_date
        mock_visit.meta = {}
        mock_visit.has_report = MagicMock(return_value=False)

        qs = MagicMock()
        qs.__iter__ = MagicMock(return_value=iter([mock_visit]))
        qs.exclude = MagicMock(return_value=qs)

        with self._patch_settings(is_active='Yes'), \
                patch(self.EMAIL_PATH) as mock_email, \
                patch.object(VisitSchedule, 'objects') as mock_objects:
            mock_objects.filter.return_value = qs
            summary, log = VisitSchedule.send_pending_report_reminders()

        mock_email.assert_called_once_with(mock_visit)
        self.assertIn('1', summary)

    def test_already_reminded_recently_skips(self):
        """Visit reminded 2 days ago with a 7-day window → no email."""
        today = datetime.date.today()
        past_date = datetime.datetime.combine(
            today - datetime.timedelta(days=10),
            datetime.time(9, 0),
        )
        two_days_ago = (today - datetime.timedelta(days=2)).strftime('%m/%d/%Y')

        mock_visit = MagicMock(spec=VisitSchedule)
        mock_visit.pk = 'test-pk-2'
        mock_visit.visit_date = past_date
        mock_visit.meta = {'reminder_last_sent_on': two_days_ago}
        mock_visit.has_report = MagicMock(return_value=False)

        qs = MagicMock()
        qs.__iter__ = MagicMock(return_value=iter([mock_visit]))
        qs.exclude = MagicMock(return_value=qs)

        with self._patch_settings(is_active='Yes', reminder_every_days=7), \
                patch(self.EMAIL_PATH) as mock_email, \
                patch.object(VisitSchedule, 'objects') as mock_objects:
            mock_objects.filter.return_value = qs
            summary, log = VisitSchedule.send_pending_report_reminders()

        mock_email.assert_not_called()
        self.assertIn('0', summary)
