"""Verify URL names resolve to the correct views."""
import uuid
from django.test import TestCase
from django.urls import reverse, resolve, NoReverseMatch


class FacultyClassVisitURLsTest(TestCase):

    def test_visits_index_resolves(self):
        url = reverse('faculty_class_visit:visits')
        self.assertIn('visits', url)

    def test_manage_visit_resolves(self):
        section_id = uuid.uuid4()
        url = reverse('faculty_class_visit:manage_visit', kwargs={'class_section_id': section_id})
        self.assertIn(str(section_id), url)

    def test_edit_visit_resolves(self):
        section_id = uuid.uuid4()
        visit_id = uuid.uuid4()
        url = reverse('faculty_class_visit:edit_visit', kwargs={
            'class_section_id': section_id, 'visit_id': visit_id
        })
        self.assertIn(str(visit_id), url)

    def test_edit_visit_report_resolves(self):
        visit_id = uuid.uuid4()
        url = reverse('faculty_class_visit:edit_visit_report', kwargs={'visit_id': visit_id})
        self.assertIn(str(visit_id), url)

    def test_delete_visit_resolves(self):
        visit_id = uuid.uuid4()
        url = reverse('faculty_class_visit:delete_visit', kwargs={'visit_id': visit_id})
        self.assertIn(str(visit_id), url)

    def test_bulk_action_resolves(self):
        url = reverse('faculty_class_visit:bulk_action')
        self.assertIn('bulk_action', url)
