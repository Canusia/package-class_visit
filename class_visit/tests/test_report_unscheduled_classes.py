# webapp/class_visit/class_visit/tests/test_report_unscheduled_classes.py
import datetime
from unittest.mock import MagicMock, patch, call

from django.test import TestCase

from class_visit.class_visit.reports.unscheduled_classes import unscheduled_classes


class UnscheduledClassesReportTest(TestCase):

    def test_row_format(self):
        form = unscheduled_classes()
        section = MagicMock()
        section.class_number = 'CRN777'
        section.course.name = 'Calculus I'
        section.term.label = 'Fall 2025'
        section.highschool.name = 'Lincoln High'
        section.status = 'A'
        row = form._row(section)
        self.assertEqual(row[0], 'CRN777')
        self.assertEqual(row[1], 'Calculus I')
        self.assertEqual(row[2], 'Fall 2025')
        self.assertEqual(row[3], 'Lincoln High')
        self.assertEqual(row[4], 'A')

    def test_queryset_method_exists(self):
        form = unscheduled_classes()
        self.assertTrue(hasattr(form, '_get_queryset'))


class UnscheduledClassesStatusMappingTest(TestCase):
    """_get_queryset maps 'active'/'inactive'/'all' settings value to DB codes 'A'/'C'."""

    def _call_get_queryset(self, status_filter_setting, term_ids=None, hs_ids=None):
        """Helper: patch dependencies and call _get_queryset, return the mock qs chain."""
        form = unscheduled_classes()
        data = {}
        if term_ids:
            data['term'] = term_ids
        if hs_ids:
            data['highschool'] = hs_ids

        # The imports inside _get_queryset are local, so patch the modules they import from.
        mock_cv_settings = MagicMock()
        mock_cv_settings.from_db.return_value = {
            'section_status_filter': status_filter_setting
        }
        mock_settings_module = MagicMock()
        mock_settings_module.class_visit = mock_cv_settings

        mock_vs = MagicMock()
        mock_vs.objects.values_list.return_value = []
        mock_nnv = MagicMock()
        mock_nnv.objects.values_list.return_value = []

        # Build a mock queryset chain that records filter/exclude calls
        mock_qs = MagicMock()
        mock_qs.exclude.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs
        mock_cs = MagicMock()
        mock_cs.objects.select_related.return_value = mock_qs

        models_module = MagicMock()
        models_module.VisitSchedule = mock_vs
        models_module.NotNeededVisit = mock_nnv

        with patch.dict('sys.modules', {
            'class_visit.class_visit.models': models_module,
            'class_visit.class_visit.settings.class_visit': mock_settings_module,
            'cis.models.section': MagicMock(**{'ClassSection': mock_cs}),
        }):
            form._get_queryset(data)
        return mock_qs

    def test_active_setting_filters_to_A(self):
        """section_status_filter='active' → filter(status__in=['A'])."""
        mock_qs = self._call_get_queryset('active')
        filter_calls = mock_qs.filter.call_args_list
        # At least one filter call must use status__in=['A']
        status_calls = [
            c for c in filter_calls
            if 'status__in' in (c.kwargs or (c[1] if len(c) > 1 else {}))
        ]
        self.assertTrue(status_calls, 'Expected a filter(status__in=...) call')
        passed_codes = (status_calls[0].kwargs or status_calls[0][1])['status__in']
        self.assertIn('A', passed_codes)
        self.assertNotIn('C', passed_codes)

    def test_inactive_setting_filters_to_C(self):
        """section_status_filter='inactive' → filter(status__in=['C'])."""
        mock_qs = self._call_get_queryset('inactive')
        filter_calls = mock_qs.filter.call_args_list
        status_calls = [
            c for c in filter_calls
            if 'status__in' in (c.kwargs or (c[1] if len(c) > 1 else {}))
        ]
        self.assertTrue(status_calls, 'Expected a filter(status__in=...) call')
        passed_codes = (status_calls[0].kwargs or status_calls[0][1])['status__in']
        self.assertIn('C', passed_codes)
        self.assertNotIn('A', passed_codes)

    def test_all_setting_does_not_filter_by_status(self):
        """section_status_filter='all' → no status__in filter applied."""
        mock_qs = self._call_get_queryset('all')
        filter_calls = mock_qs.filter.call_args_list
        status_calls = [
            c for c in filter_calls
            if 'status__in' in (c.kwargs or (c[1] if len(c) > 1 else {}))
        ]
        self.assertEqual(status_calls, [], 'No status__in filter expected when setting is all')
