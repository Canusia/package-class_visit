"""manage_visit: the selectable sections are limited to the anchor section's
course taught by the same instructor (a visit's sections must share one
instructor). Without an anchor, all overseen sections are offered (unchanged).
"""
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from cis.models.term import AcademicYear, Term
from cis.models.course import Cohort, Course, CourseAdministrator
from cis.models.section import ClassSection
from cis.models.teacher import Teacher

from class_visit.class_visit.forms.faculty import VisitScheduleForm

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class ManageVisitSectionScopeTest(TestCase):
    def setUp(self):
        self.faculty = User.objects.create_user(
            username=f'fac_{_sfx()}', email=f'fac_{_sfx()}@x.com', password='x')
        self.faculty.groups.add(Group.objects.get_or_create(name='faculty')[0])

        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        self.term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        self.course_a = Course.objects.create(
            catalog_number='101', title='A', cohort=cohort)
        self.course_b = Course.objects.create(
            catalog_number='102', title='B', cohort=cohort)

        self.t1 = Teacher.objects.create(user=User.objects.create_user(
            username=f't1_{_sfx()}', email=f't1_{_sfx()}@x.com', password='x'))
        self.t2 = Teacher.objects.create(user=User.objects.create_user(
            username=f't2_{_sfx()}', email=f't2_{_sfx()}@x.com', password='x'))

        # same course + same teacher as the anchor -> included
        self.sec_a1 = self._section(self.course_a, self.t1, '1001')
        self.sec_a2 = self._section(self.course_a, self.t1, '1002')
        # same course, DIFFERENT teacher -> excluded
        self.sec_a3 = self._section(self.course_a, self.t2, '1003')
        # DIFFERENT course, same teacher -> excluded
        self.sec_b1 = self._section(self.course_b, self.t1, '2001')

        # faculty oversees BOTH courses
        for course in (self.course_a, self.course_b):
            CourseAdministrator.objects.create(
                user=self.faculty, course=course, role='Faculty', status='Active')

    def _section(self, course, teacher, num):
        return ClassSection.objects.create(
            class_number=num, term=self.term, course=course,
            teacher=teacher, status='A')

    def _choice_ids(self, form):
        return {c[0] for c in form.fields['class_sections'].choices}

    @patch('class_visit.class_visit.forms.faculty.ClassVisitSettings')
    def test_anchor_limits_to_same_course_and_instructor(self, MockSettings):
        MockSettings.from_db.return_value = {
            'section_status_filter': 'active', 'visit_types': 'Observation'}
        form = VisitScheduleForm(
            faculty_user=self.faculty, anchor_section=self.sec_a1)
        ids = self._choice_ids(form)
        self.assertEqual(ids, {str(self.sec_a1.id), str(self.sec_a2.id)})
        self.assertNotIn(str(self.sec_a3.id), ids)   # same course, other teacher
        self.assertNotIn(str(self.sec_b1.id), ids)   # other course, same teacher
        # new visit pre-selects the section it was launched from
        self.assertEqual(form.fields['class_sections'].initial, [str(self.sec_a1.id)])

    @patch('class_visit.class_visit.forms.faculty.ClassVisitSettings')
    def test_without_anchor_all_overseen_sections_offered(self, MockSettings):
        MockSettings.from_db.return_value = {
            'section_status_filter': 'active', 'visit_types': 'Observation'}
        form = VisitScheduleForm(faculty_user=self.faculty)
        ids = self._choice_ids(form)
        self.assertEqual(
            ids,
            {str(self.sec_a1.id), str(self.sec_a2.id),
             str(self.sec_a3.id), str(self.sec_b1.id)},
        )
