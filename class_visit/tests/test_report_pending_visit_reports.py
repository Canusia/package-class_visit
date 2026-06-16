# webapp/class_visit/class_visit/tests/test_report_pending_visit_reports.py
import datetime
from unittest.mock import MagicMock, patch, PropertyMock

from django.test import TestCase

from class_visit.class_visit.reports.pending_visit_reports import pending_visit_reports


class PendingVisitReportsReportTest(TestCase):

    def _make_visit(self, visit_date, has_report=False, report_status=None):
        visit = MagicMock()
        visit.visit_date = visit_date
        visit.type_of_visit = 'Observation'
        teacher = MagicMock()
        teacher.get_full_name.return_value = 'Carol White'
        visit.teacher = teacher
        visit.class_sections.all.return_value = [MagicMock(class_number='CRN555')]
        visit.visitors.all.return_value = [MagicMock(get_full_name=lambda: 'Dave')]
        if has_report:
            visit.report = MagicMock(status=report_status)
        else:
            type(visit).report = PropertyMock(
                side_effect=type('VisitReport.DoesNotExist', (Exception,), {})()
            )
        return visit

    def test_row_includes_days_past(self):
        form = pending_visit_reports()
        today = datetime.date.today()
        past = today - datetime.timedelta(days=5)
        visit = self._make_visit(past, has_report=False)
        row = form._row(visit, today)
        # days_past column should be 5
        days_past_col = row[2]   # 3rd column: Days Past Visit
        self.assertEqual(int(days_past_col), 5)

    def test_row_draft_shows_draft_status(self):
        form = pending_visit_reports()
        today = datetime.date.today()
        past = today - datetime.timedelta(days=3)
        visit = self._make_visit(past, has_report=True, report_status='Draft')
        row = form._row(visit, today)
        self.assertIn('Draft', row)

    def test_row_no_report_shows_missing(self):
        form = pending_visit_reports()
        today = datetime.date.today()
        past = today - datetime.timedelta(days=2)
        visit = self._make_visit(past, has_report=False)
        row = form._row(visit, today)
        self.assertIn('Missing', row)
