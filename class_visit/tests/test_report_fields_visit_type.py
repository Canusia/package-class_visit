from unittest.mock import patch
from django.test import TestCase

from class_visit.class_visit.services import report_fields

DEFS = [
    {'name': 'always', 'label': 'Always', 'type': 'text'},                       # no visit_types -> all
    {'name': 'initial_only', 'label': 'Initial Only', 'type': 'text', 'visit_types': ['Initial']},
    {'name': 'multi', 'label': 'Multi', 'type': 'text', 'visit_types': ['Initial', 'Follow-up']},
]


class ReportFieldVisitTypeTests(TestCase):
    def _patch(self):
        return patch.object(report_fields, 'get_report_field_defs', wraps=None)

    @patch('class_visit.class_visit.services.report_fields._get_settings')
    def test_filters_by_visit_type(self, mock_settings):
        import json
        mock_settings.return_value = {'report_fields_json': json.dumps(DEFS)}
        names = [d['name'] for d in report_fields.get_report_field_defs(type_of_visit='Initial')]
        self.assertEqual(names, ['always', 'initial_only', 'multi'])

    @patch('class_visit.class_visit.services.report_fields._get_settings')
    def test_excludes_nonmatching_type(self, mock_settings):
        import json
        mock_settings.return_value = {'report_fields_json': json.dumps(DEFS)}
        names = [d['name'] for d in report_fields.get_report_field_defs(type_of_visit='Annual')]
        self.assertEqual(names, ['always'])  # only the untargeted field

    @patch('class_visit.class_visit.services.report_fields._get_settings')
    def test_none_type_returns_all(self, mock_settings):
        import json
        mock_settings.return_value = {'report_fields_json': json.dumps(DEFS)}
        names = [d['name'] for d in report_fields.get_report_field_defs()]
        self.assertEqual(names, ['always', 'initial_only', 'multi'])
