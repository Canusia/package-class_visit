"""Regression: the faculty /class_sections/ API must not crash on evaluation.

`ClassSection.syllabi` is a @property (not a relation), so
`prefetch_related('syllabi')` raised
    ValueError: 'syllabi' does not resolve to an item that supports prefetching
when the DataTables queryset was evaluated. The existing faculty view tests
mock `ClassSection`, so the prefetch runs on a MagicMock and never trips this;
this test uses REAL models and forces evaluation.
"""
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, RequestFactory

from cis.models.term import AcademicYear, Term
from cis.models.course import Cohort, Course, CourseAdministrator
from cis.models.section import ClassSection

from class_visit.class_visit.views.faculty import FacultySchedulableSectionViewSet

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class SchedulableSectionPrefetchTest(TestCase):
    @patch('class_visit.class_visit.views.faculty.ClassVisitSettings')
    def test_get_queryset_evaluates_without_syllabi_prefetch_error(self, MockSettings):
        MockSettings.from_db.return_value = {'section_status_filter': 'active'}

        faculty = User.objects.create_user(
            username=f'fac_{_sfx()}', email=f'fac_{_sfx()}@x.com', password='x')
        faculty.groups.add(Group.objects.get_or_create(name='faculty')[0])

        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        course = Course.objects.create(
            catalog_number='101', title='Intro', cohort=cohort)
        section = ClassSection.objects.create(
            class_number='1001', term=term, course=course, status='A')
        CourseAdministrator.objects.create(
            user=faculty, course=course, role='Faculty', status='Active')

        vs = FacultySchedulableSectionViewSet()
        req = RequestFactory().get('/faculty/class_visits/api/class_sections/')
        req.user = faculty
        vs.request = req
        vs.format_kwarg = None
        vs.kwargs = {}

        # Forcing evaluation is what raised the ValueError before the fix.
        result = list(vs.get_queryset())
        self.assertIn(section, result)
