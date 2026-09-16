"""The CE scheduling form honours the same two rules the faculty form does (#12).

`CEVisitScheduleForm` ignored both `section_status_filter` and the NotNeededVisit
exemption list, so a tenant configuring "active sections only" found it silently did not
apply to CE staff, and a section explicitly flagged "visit not needed" stayed fully
schedulable from the CE side. The faculty form honours both.

The edit carve-out is the part worth guarding: a section already attached to the visit
being edited must stay in the choices even when the filters would now exclude it.
Otherwise the form drops it and saving rewrites the visit without it — a display filter
silently becoming data loss.
"""
import uuid

from django.test import TestCase

from cis.models.course import Cohort, Course
from cis.models.section import ClassSection
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term
from django.contrib.auth import get_user_model

from unittest.mock import patch

from . import PKG
from ..forms.ce import CEVisitScheduleForm
from ..models import NotNeededVisit, VisitSchedule

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class CEFormParityTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        cls.term = Term.objects.create(
            academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        cls.course = Course.objects.create(
            catalog_number='101', title='A', cohort=cohort)
        cls.teacher = Teacher.objects.create(user=User.objects.create_user(
            username=f't_{_sfx()}', email=f't_{_sfx()}@x.com', password='x'))

        cls.anchor = cls._section('001', status='A')
        cls.sibling_active = cls._section('002', status='A')
        cls.sibling_inactive = cls._section('003', status='C')
        cls.sibling_not_needed = cls._section('004', status='A')
        NotNeededVisit.objects.create(class_section=cls.sibling_not_needed)

    @classmethod
    def _section(cls, number, status):
        return ClassSection.objects.create(
            course=cls.course, term=cls.term, teacher=cls.teacher,
            class_number=f'C-{_sfx()}', section_number=number, status=status)

    def _choices(self, settings_dict=None, visit_id=None):
        settings_dict = settings_dict or {'section_status_filter': 'active',
                                          'visit_types': 'Initial|Follow-up'}
        with patch(f'{PKG}.forms.ce.ClassVisitSettings.from_db',
                   return_value=settings_dict):
            form = CEVisitScheduleForm(
                section_id=self.anchor.id, visit_id=visit_id)
        return {value for value, _label in form.fields['class_sections'].choices}

    def test_anchor_section_is_offered_and_preselected(self):
        with patch(f'{PKG}.forms.ce.ClassVisitSettings.from_db',
                   return_value={'section_status_filter': 'active',
                                 'visit_types': 'Initial'}):
            form = CEVisitScheduleForm(section_id=self.anchor.id)

        values = {v for v, _ in form.fields['class_sections'].choices}
        self.assertIn(str(self.anchor.id), values)
        self.assertEqual(form.fields['class_sections'].initial, [str(self.anchor.id)])

    def test_inactive_sibling_is_excluded_under_active_filter(self):
        self.assertNotIn(str(self.sibling_inactive.id), self._choices())

    def test_inactive_sibling_is_included_under_all_filter(self):
        choices = self._choices({'section_status_filter': 'all',
                                 'visit_types': 'Initial'})
        self.assertIn(str(self.sibling_inactive.id), choices)

    def test_not_needed_sibling_is_excluded(self):
        self.assertNotIn(str(self.sibling_not_needed.id), self._choices())

    def test_ordinary_active_sibling_is_still_offered(self):
        self.assertIn(str(self.sibling_active.id), self._choices())

    # -- the edit carve-out --------------------------------------------------

    def test_editing_keeps_a_section_the_filters_would_now_exclude(self):
        visit = VisitSchedule.objects.create(
            visit_date='2026-03-01', type_of_visit='Initial', meta={})
        visit.class_sections.add(self.anchor, self.sibling_inactive)

        choices = self._choices(visit_id=visit.id)

        self.assertIn(str(self.sibling_inactive.id), choices,
                      'a section already on the visit must stay selectable')

    def test_editing_keeps_a_not_needed_section_already_on_the_visit(self):
        visit = VisitSchedule.objects.create(
            visit_date='2026-03-01', type_of_visit='Initial', meta={})
        visit.class_sections.add(self.anchor, self.sibling_not_needed)

        self.assertIn(str(self.sibling_not_needed.id), self._choices(visit_id=visit.id))

    def test_creating_does_not_resurrect_excluded_sections(self):
        # visit_id='-1' is the create sentinel the view passes.
        self.assertNotIn(str(self.sibling_inactive.id), self._choices(visit_id='-1'))
