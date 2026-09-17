"""class_visit must still load and scope on a cis that predates FacultyTeacherAssignment.

The model arrived in package-cis v0.0.20 (migration 0078). Tenants still running an
older or in-tree cis -- ewu main at the time of writing -- would otherwise fail at URLconf
import, because views/faculty.py and forms/faculty.py import services.scope at module
load. Without the model there is no faculty->teacher mapping to honour, so scoping
falls back to course-only, which is exactly what an unconfigured tenant gets anyway.
"""
import importlib
import sys
import types
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from cis.models.course import Cohort, Course, CourseAdministrator
from cis.models.section import ClassSection
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from ..services import scope

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class ScopeImportWithoutAssignmentModelTest(SimpleTestCase):

    def test_scope_imports_when_cis_has_no_faculty_teacher_assignment(self):
        old_cis_faculty = types.ModuleType('cis.models.faculty')
        # Restore the real module state however this test exits.
        self.addCleanup(importlib.reload, scope)

        with mock.patch.dict(sys.modules, {'cis.models.faculty': old_cis_faculty}):
            importlib.reload(scope)

        self.assertIsNone(scope.FacultyTeacherAssignment)


class ScopedSectionsWithoutAssignmentModelTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        cls.course = Course.objects.create(catalog_number='101', title='A', cohort=cohort)
        cls.section_a = cls._section(term, '001')
        cls.section_b = cls._section(term, '002')

    @classmethod
    def _section(cls, term, number):
        teacher = Teacher.objects.create(user=User.objects.create_user(
            username=f't_{_sfx()}', email=f't_{_sfx()}@x.com', password='x'))
        return ClassSection.objects.create(
            course=cls.course, term=term, teacher=teacher,
            class_number=f'C-{_sfx()}', section_number=number, status='A')

    def _user_with_role(self, role):
        user = User.objects.create_user(
            username=f'u_{_sfx()}', email=f'u_{_sfx()}@x.com', password='x')
        CourseAdministrator.objects.create(
            user=user, course=self.course, role=role, status='Active')
        return user

    def test_course_only_scope_when_the_model_is_absent(self):
        user = self._user_with_role('Faculty')

        with mock.patch.object(scope, 'FacultyTeacherAssignment', None):
            ids = set(scope.scoped_sections(user).values_list('id', flat=True))

        self.assertEqual(ids, {self.section_a.id, self.section_b.id})

    def test_role_filter_still_applies_when_the_model_is_absent(self):
        user = self._user_with_role('Administrator')

        with mock.patch.object(scope, 'FacultyTeacherAssignment', None):
            self.assertFalse(scope.scoped_sections(user).exists())
