# webapp/class_visit/class_visit/tests/test_report_scheduled_visits.py
import datetime
from unittest.mock import MagicMock, patch

from django.test import TestCase

from class_visit.class_visit.reports.scheduled_visits import scheduled_visits


class ScheduledVisitsReportTest(TestCase):
    """Unit-test the row-builder logic without hitting S3."""

    def _make_visit(self, visit_date, type_of_visit, crns, visitors, report_status=None):
        """Return a mock VisitSchedule-like object."""
        sections = [MagicMock(class_number=crn) for crn in crns]
        visitor_objs = [
            MagicMock(get_full_name=lambda n=n: n) for n in visitors
        ]
        teacher = MagicMock(get_full_name=MagicMock(return_value='Jane Smith'))
        visit = MagicMock()
        visit.visit_date = visit_date
        visit.type_of_visit = type_of_visit
        visit.class_sections.all.return_value = sections
        visit.visitors.all.return_value = visitor_objs
        visit.teacher = teacher
        if report_status:
            visit.report = MagicMock(status=report_status)
        else:
            # Simulate no related report (DoesNotExist via AttributeError on access)
            del visit.report
            type(visit).report = property(
                lambda self: (_ for _ in ()).throw(
                    type('VisitReport.DoesNotExist', (Exception,), {})()
                )
            )
        return visit

    def _row_for(self, visit):
        form = scheduled_visits()
        return form._row(visit)

    def test_row_includes_visit_date_and_type(self):
        visit = self._make_visit(
            datetime.date(2025, 3, 15), 'Observation', ['CRN101'], ['Alice'], 'Submitted'
        )
        row = self._row_for(visit)
        self.assertEqual(row[0], '03/15/2025')
        self.assertEqual(row[1], 'Observation')

    def test_row_joins_crns(self):
        visit = self._make_visit(
            datetime.date(2025, 3, 15), 'Observation', ['CRN101', 'CRN202'], ['Alice'], 'Submitted'
        )
        row = self._row_for(visit)
        self.assertIn('CRN101', row[2])
        self.assertIn('CRN202', row[2])

    def test_row_shows_no_report_when_missing(self):
        visit = self._make_visit(
            datetime.date(2025, 3, 15), 'Observation', ['CRN101'], ['Alice'], None
        )
        row = self._row_for(visit)
        self.assertEqual(row[-1], 'No Report')

    def test_row_shows_submitted_status(self):
        visit = self._make_visit(
            datetime.date(2025, 3, 15), 'Observation', ['CRN101'], ['Alice'], 'Submitted'
        )
        row = self._row_for(visit)
        self.assertEqual(row[-1], 'Submitted')
