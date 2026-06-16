"""Smoke tests for faculty serializers: required fields present."""
import uuid
from unittest.mock import MagicMock, patch, PropertyMock
from django.test import TestCase


class FacultySchedulableSectionSerializerTest(TestCase):

    def test_import(self):
        from class_visit.class_visit.serializers.faculty import (
            FacultySchedulableSectionSerializer
        )
        self.assertTrue(callable(FacultySchedulableSectionSerializer))

    def test_meta_has_datatables_always_serialize(self):
        from class_visit.class_visit.serializers.faculty import (
            FacultySchedulableSectionSerializer
        )
        meta = FacultySchedulableSectionSerializer.Meta
        self.assertTrue(hasattr(meta, 'datatables_always_serialize'))
        always = meta.datatables_always_serialize
        for required in ['id', 'course', 'term', 'teacher', 'visit_schedule']:
            self.assertIn(required, always, f'{required} missing from datatables_always_serialize')


class FacultyVisitScheduleSerializerTest(TestCase):

    def test_import(self):
        from class_visit.class_visit.serializers.faculty import (
            FacultyVisitScheduleSerializer
        )
        self.assertTrue(callable(FacultyVisitScheduleSerializer))

    def test_meta_has_datatables_always_serialize(self):
        from class_visit.class_visit.serializers.faculty import (
            FacultyVisitScheduleSerializer
        )
        meta = FacultyVisitScheduleSerializer.Meta
        self.assertTrue(hasattr(meta, 'datatables_always_serialize'))
        always = meta.datatables_always_serialize
        for required in ['id', 'visit_date', 'class_sections', 'visitors',
                         'manage_visit_url', 'edit_report_url', 'delete_url',
                         'has_started_report', 'has_submitted_report']:
            self.assertIn(required, always, f'{required} missing')
