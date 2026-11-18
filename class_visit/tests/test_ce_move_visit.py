"""#26: CE moves a visit (and its report) to a different class section from
Edit Visit, without impersonating the visitor; teacherless sections give a
validation error instead of a 500."""
from unittest.mock import patch

from django.core import mail
from django.test import Client
from django.urls import reverse

from cis.models.section import ClassSection
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from . import PKG
from .test_ce_schedule_on_behalf import SETTINGS, _Fixture, _sfx, _user
from ..forms.ce import CEVisitScheduleForm
from ..models import VisitReport, VisitSchedule


class _MoveFixture(_Fixture):
    """An old teacherless section (last year) holding a submitted visit, and
    this year's section at the same school with a teacher."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        old_ay = AcademicYear.objects.create(name=f'AY-old-{_sfx()}')
        cls.old_term = Term.objects.create(
            academic_year=old_ay, code='FA-old', label=f'Fall-old-{_sfx()}')
        cls.old_section = ClassSection.objects.create(
            course=cls.course, term=cls.old_term, teacher=None,
            class_number=f'C-{_sfx()}', section_number='001', status='A')

        cls.visit = VisitSchedule.objects.create(
            visit_date='2026-10-01', type_of_visit='Initial', meta={})
        cls.visit.class_sections.add(cls.old_section)
        cls.visit.visitors.add(cls.faculty)
        cls.report = VisitReport.objects.create(
            visit_schedule=cls.visit, status='Submitted', meta={'summary': 'kept'})

    def setUp(self):
        self.client = Client(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.ce_user)
        p = patch(f'{PKG}.forms.ce.ClassVisitSettings.from_db', return_value=SETTINGS)
        p.start()
        self.addCleanup(p.stop)

    def _move_url(self, section=None):
        return reverse('class_visit:ce_move_visit', kwargs={
            'visit_id': self.visit.id, 'section_id': (section or self.section).id})

    def _post(self, sections):
        return self.client.post(self._move_url(), {
            'class_sections': [str(s.id) for s in sections],
            'visitors': [str(self.faculty.id)],
            'visit_date': '2026-10-01',
            'type_of_visit': 'Initial',
            'visit_id': str(self.visit.id),
        })


class TeacherlessSectionsValidationTest(_MoveFixture):

    def test_share_teacher_is_false_not_an_error(self):
        self.assertFalse(VisitSchedule.sections_share_teacher(
            [self.old_section, self.section]))
        self.assertFalse(VisitSchedule.sections_share_teacher(
            [self.section, self.old_section]))
        self.assertTrue(VisitSchedule.sections_share_teacher([self.old_section]))

    def test_ce_form_gives_a_validation_error(self):
        resp = self._post([self.old_section, self.section])
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()['success'])
        self.assertIn('same instructor', resp.json()['errors'])
        self.assertEqual(set(self.visit.class_sections.all()), {self.old_section})


class MoveFormTest(_MoveFixture):

    def _form(self, **kw):
        return CEVisitScheduleForm(section_id=self.section.id, visit_id=self.visit.id, **kw)

    def test_new_section_is_offered_and_preselected(self):
        form = self._form()
        choices = dict(form.fields['class_sections'].choices)
        self.assertIn(str(self.section.id), choices)
        self.assertEqual(form.fields['class_sections'].initial, [str(self.section.id)])

    def test_current_section_stays_listed_and_labelled(self):
        choices = dict(self._form().fields['class_sections'].choices)
        self.assertIn('currently scheduled', str(choices[str(self.old_section.id)]))

    def test_plain_edit_keeps_the_current_sections_selected(self):
        form = CEVisitScheduleForm(section_id=self.old_section.id, visit_id=self.visit.id)
        self.assertEqual(form.fields['class_sections'].initial, [str(self.old_section.id)])


class MoveViewTest(_MoveFixture):

    def test_move_keeps_the_report_and_sends_no_email(self):
        resp = self._post([self.section])
        self.assertTrue(resp.json()['success'], resp.json())
        self.visit.refresh_from_db()
        self.assertEqual(set(self.visit.class_sections.all()), {self.section})
        self.assertEqual(set(self.visit.visitors.all()), {self.faculty})
        report = VisitReport.objects.get(pk=self.report.pk)
        self.assertEqual(report.visit_schedule_id, self.visit.id)
        self.assertEqual(report.status, 'Submitted')
        self.assertEqual(report.meta, {'summary': 'kept'})
        self.assertEqual(len(mail.outbox), 0)

    def test_move_is_recorded(self):
        self._post([self.section])
        self.visit.refresh_from_db()
        changes = self.visit.meta['section_changes']
        self.assertEqual(len(changes), 1)
        entry = changes[0]
        self.assertEqual(entry['by_id'], self.ce_user.id)
        self.assertEqual(entry['from_ids'], [str(self.old_section.id)])
        self.assertEqual(entry['to_ids'], [str(self.section.id)])
        self.assertTrue(entry['at'])

    def test_edit_without_a_section_change_records_nothing(self):
        self.client.post(reverse('class_visit:ce_edit_visit', args=[self.visit.id]), {
            'class_sections': [str(self.old_section.id)],
            'visitors': [str(self.faculty.id)], 'visit_date': '2026-10-02',
            'type_of_visit': 'Initial', 'visit_id': str(self.visit.id)})
        self.visit.refresh_from_db()
        self.assertNotIn('section_changes', self.visit.meta)

    def test_unknown_visit_is_404(self):
        import uuid
        resp = self.client.get(reverse('class_visit:ce_move_visit', kwargs={
            'visit_id': uuid.uuid4(), 'section_id': self.section.id}))
        self.assertEqual(resp.status_code, 404)

    def test_non_ce_user_refused(self):
        self.client.force_login(self.faculty)
        resp = self.client.get(self._move_url())
        self.assertNotEqual(resp.status_code, 200)

    def test_edit_page_links_to_change_section(self):
        html = self.client.get(
            reverse('class_visit:ce_edit_visit', args=[self.visit.id])).content.decode()
        self.assertIn(
            reverse('class_visit:ce_schedule_picker') + f'?move_visit={self.visit.id}', html)


class MovePickerTest(_MoveFixture):

    def _picker(self, **params):
        with patch(f'{PKG}.views.ce.ClassVisitSettings.from_db', return_value=SETTINGS):
            return self.client.get(reverse('class_visit:ce_schedule_picker'), {
                'move_visit': str(self.visit.id), 'term_id': '', **params}).content.decode()

    def test_rows_link_to_the_move_url(self):
        html = self._picker()
        self.assertIn(self._move_url(), html)
        self.assertNotIn(
            reverse('class_visit:ce_manage_visit', kwargs={'section_id': self.section.id}),
            html)

    def test_defaults_to_the_visits_course(self):
        from cis.models.course import Course
        other = Course.objects.create(
            catalog_number='999', title='Other', cohort=self.course.cohort)
        other_section = ClassSection.objects.create(
            course=other, term=self.term, teacher=self.teacher,
            class_number=f'C-{_sfx()}', section_number='009', status='A')
        html = self._picker()
        self.assertNotIn(str(other_section.id), html)
        self.assertIn(str(other_section.id), self._picker(course_id=''))

    def test_search_narrows_rows(self):
        html = self._picker(q=self.section.class_number)
        self.assertIn(str(self.section.id), html)
        self.assertNotIn(str(self.old_section.id), html)

    def test_term_column_shows_the_academic_year(self):
        self.assertIn(self.term.academic_year.name, self._picker())
