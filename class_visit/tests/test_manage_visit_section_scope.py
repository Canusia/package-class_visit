"""manage_visit: the selectable sections are limited to the anchor section's
course taught by the same instructor (a visit's sections must share one
instructor). Without an anchor, all overseen sections are offered (unchanged).
"""
import uuid
from unittest.mock import patch

from django import forms as djforms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.template.loader import render_to_string
from django.test import TestCase, SimpleTestCase

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
    def test_template_renders_form_with_crispy(self, MockSettings):
        from django.template.loader import render_to_string
        MockSettings.from_db.return_value = {
            'section_status_filter': 'active', 'visit_types': 'Observation'}
        form = VisitScheduleForm(
            faculty_user=self.faculty, anchor_section=self.sec_a1)
        html = render_to_string(
            'class_visit/faculty/manage_visit.html',
            {'form': form, 'page_title': 'Schedule / Edit Visit'})
        self.assertIn('id="manage_visit_form"', html)
        self.assertIn('form-group', html)              # crispy bootstrap4 wrapper
        self.assertIn('name="class_sections"', html)

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


class ReportTemplateRenderTest(SimpleTestCase):
    """The add/edit report form renders with crispy + the app CSS (no DB)."""

    @patch('class_visit.class_visit.forms.faculty.report_fields.build_report_form_fields')
    def test_report_template_renders_with_crispy(self, mock_build):
        from class_visit.class_visit.forms.faculty import VisitReportDynamicForm
        mock_build.return_value = {
            'summary': djforms.CharField(label='Summary', widget=djforms.Textarea),
        }
        form = VisitReportDynamicForm(visit=None)
        html = render_to_string(
            'class_visit/faculty/edit_visit_report.html',
            {'form': form, 'page_title': 'Class Visit Report'})
        self.assertIn('id="report_form"', html)
        self.assertIn('form-group', html)             # crispy styled the dynamic field
        self.assertIn('name="submit_action"', html)   # hidden action field present
        self.assertIn('Submit Report', html)
        self.assertIn('Save as Draft', html)
        # app CSS is wired (so crispy classes actually render)
        self.assertIn('sb-admin-2.min.css', html)
