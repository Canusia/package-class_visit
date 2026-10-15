"""EWU feedback round, 2026-10 (docs/plans/class-visit-ewu-feedback-2026-10.md in ewu).

- Term filters follow the parent/sub-term hierarchy: EWU's active term is a parent whose
  sections all sit on sub-terms, so an exact-term filter showed no visits at all.
- A teacherless anchor section no longer offers every teacherless section in the course.
- Faculty "My Visits" lists only visits they are a visitor on; other faculty's visits are a
  separate read-only list behind the `faculty_view_others_visits` setting.
- Touching someone else's visit gets a clear refusal, not a bare 404.
"""
import datetime
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import Client, TestCase
from django.urls import reverse

from cis.models.course import Cohort, Course, CourseAdministrator
from cis.models.section import ClassSection
from cis.models.settings import Setting
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from ..forms.ce import CEVisitScheduleForm
from ..forms.faculty import VisitScheduleForm
from ..models import VisitReport, VisitSchedule
from ..services import terms as term_service

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


def _user(group, **extra):
    user = User.objects.create_user(
        username=f'{group}_{_sfx()}', email=f'{group}_{_sfx()}@x.com', password='x',
        **extra)
    user.groups.add(Group.objects.get_or_create(name=group)[0])
    return user


class _Base(TestCase):
    @classmethod
    def setUpClass(cls):
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    def setUp(self):
        self.client = Client(REMOTE_ADDR='127.0.0.1')

    @classmethod
    def setUpTestData(cls):
        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        cls.parent_term = Term.objects.create(
            academic_year=ay, code=f'P{_sfx()[:4]}', label='Fall Quarter')
        cls.sub_term = Term.objects.create(
            academic_year=ay, code=f'S{_sfx()[:4]}', label='Fall Semester',
            parent=cls.parent_term)
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        cls.course = Course.objects.create(catalog_number='101', title='A', cohort=cohort)

        cls.teacher = Teacher.objects.create(user=User.objects.create_user(
            username=f't_{_sfx()}', email=f't_{_sfx()}@x.com', password='x'))
        cls.section = cls._section(cls.teacher)
        # Two teacherless sections in the same course and term.
        cls.bare_a = cls._section(None)
        cls.bare_b = cls._section(None)

        cls.me = _user('faculty', first_name='Me', last_name='Faculty')
        cls.colleague = _user('faculty', first_name='Col', last_name='League')
        cls.outsider = _user('faculty')
        for user in (cls.me, cls.colleague):
            CourseAdministrator.objects.create(
                user=user, course=cls.course, role='Faculty', status='Active')

        cls.my_visit = cls._visit(cls.section, cls.me)
        cls.their_visit = cls._visit(cls.section, cls.colleague)
        VisitReport.objects.create(
            visit_schedule=cls.their_visit, status='Submitted', meta={},
            teacher_discussion='', student_discussion='', visit_letter='')

    @classmethod
    def _section(cls, teacher):
        return ClassSection.objects.create(
            course=cls.course, term=cls.sub_term, teacher=teacher,
            class_number=f'C-{_sfx()}', section_number='001', status='A')

    @classmethod
    def _visit(cls, section, visitor):
        visit = VisitSchedule.objects.create(
            visit_date=datetime.date(2026, 10, 1), type_of_visit='Initial', meta={})
        visit.class_sections.add(section)
        visit.visitors.add(visitor)
        return visit

    def _settings(self, **values):
        Setting.objects.update_or_create(
            key='class_visit', defaults={'value': {'section_status_filter': 'active', **values}})

    def _rows(self, url):
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        rows = resp.json()
        rows = rows['results'] if isinstance(rows, dict) else rows
        return {row['id'] for row in rows}


class TermHierarchyTest(_Base):
    def test_service_filter_includes_sub_terms(self):
        qs = term_service.filter_by_term(
            ClassSection.objects.all(), str(self.parent_term.id))
        self.assertIn(self.section, qs)

    def test_choices_indent_sub_terms_under_parent(self):
        choices = term_service.term_choices([self.parent_term, self.sub_term])
        self.assertEqual([c[0] for c in choices],
                         [str(self.parent_term.id), str(self.sub_term.id)])
        self.assertTrue(choices[1][1].startswith(' ') or choices[1][1].startswith(' '))

    def test_ce_api_parent_term_finds_visits_on_sub_terms(self):
        self.client.force_login(_user('ce'))
        ids = self._rows(
            f'/ce/class_visits/api/visit_schedule/?format=json&term_id={self.parent_term.id}')
        self.assertEqual(ids, {str(self.my_visit.id), str(self.their_visit.id)})

    def test_faculty_api_parent_term_finds_visits_on_sub_terms(self):
        self.client.force_login(self.me)
        ids = self._rows(
            f'/faculty/class_visits/api/visit_schedule/?format=json&term_id={self.parent_term.id}')
        self.assertEqual(ids, {str(self.my_visit.id)})


class TeacherlessSectionChoicesTest(_Base):
    def test_ce_form_offers_only_the_anchor_when_it_has_no_teacher(self):
        self._settings()
        form = CEVisitScheduleForm(section_id=self.bare_a.id)
        offered = {c[0] for c in form.fields['class_sections'].choices}
        self.assertEqual(offered, {str(self.bare_a.id)})

    def test_ce_form_keeps_sections_already_on_the_visit(self):
        self._settings()
        visit = self._visit(self.bare_a, self.me)
        visit.class_sections.add(self.bare_b)
        form = CEVisitScheduleForm(section_id=self.bare_a.id, visit_id=visit.id)
        offered = {c[0] for c in form.fields['class_sections'].choices}
        self.assertEqual(offered, {str(self.bare_a.id), str(self.bare_b.id)})

    def test_faculty_form_offers_only_the_anchor_when_it_has_no_teacher(self):
        self._settings()
        form = VisitScheduleForm(faculty_user=self.me, anchor_section=self.bare_a)
        offered = {c[0] for c in form.fields['class_sections'].choices}
        self.assertEqual(offered, {str(self.bare_a.id)})


class FacultySchedulingVisitorsTest(_Base):
    def test_new_visit_pre_checks_the_scheduling_faculty(self):
        self._settings()
        form = VisitScheduleForm(faculty_user=self.me, anchor_section=self.section)
        self.assertEqual(form.fields['visitors'].initial, [str(self.me.id)])

    def test_other_visitors_are_the_other_active_faculty_for_the_course(self):
        self._settings()
        form = VisitScheduleForm(faculty_user=self.me, anchor_section=self.section)
        offered = {c[0] for c in form.fields['visitors'].choices}
        self.assertEqual(offered, {str(self.me.id), str(self.colleague.id)})


class FacultyVisitListsTest(_Base):
    API = '/faculty/class_visits/api/visit_schedule/?format=json'

    def test_my_visits_lists_only_visits_i_am_a_visitor_on(self):
        self.client.force_login(self.me)
        self.assertEqual(self._rows(self.API), {str(self.my_visit.id)})

    def test_others_list_is_empty_when_the_setting_is_off(self):
        self._settings(faculty_view_others_visits='No')
        self.client.force_login(self.me)
        self.assertEqual(self._rows(self.API + '&scope=others'), set())

    def test_others_list_shows_colleagues_visits_when_on(self):
        self._settings(faculty_view_others_visits='Yes')
        self.client.force_login(self.me)
        self.assertEqual(self._rows(self.API + '&scope=others'), {str(self.their_visit.id)})

    def test_others_list_stays_within_my_course_area(self):
        self._settings(faculty_view_others_visits='Yes')
        self.client.force_login(self.outsider)
        self.assertEqual(self._rows(self.API + '&scope=others'), set())

    def test_index_lists_each_visitor_once(self):
        other = Course.objects.create(
            catalog_number='102', title='B', cohort=self.course.cohort)
        CourseAdministrator.objects.create(
            user=self.colleague, course=other, role='Faculty', status='Active')
        CourseAdministrator.objects.create(
            user=self.me, course=other, role='Faculty', status='Active')
        self._settings(faculty_view_others_visits='Yes')
        self.client.force_login(self.me)
        resp = self.client.get(reverse('faculty_class_visit:visits'))
        ids = [str(u.id) for u in resp.context['visitors']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn(str(self.me.id), ids)


class OthersReportViewTest(_Base):
    def _url(self, visit):
        return reverse('faculty_class_visit:view_report', kwargs={'visit_id': visit.id})

    def test_full_read_only_report_when_on(self):
        self._settings(faculty_view_others_visits='Yes')
        self.client.force_login(self.me)
        resp = self.client.get(self._url(self.their_visit))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Submit Report')

    def test_404_when_off(self):
        self._settings(faculty_view_others_visits='No')
        self.client.force_login(self.me)
        self.assertEqual(self.client.get(self._url(self.their_visit)).status_code, 404)

    def test_404_outside_my_course_area(self):
        self._settings(faculty_view_others_visits='Yes')
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self._url(self.their_visit)).status_code, 404)


class OthersFileDownloadTest(_Base):
    """Colleagues read submitted reports only -- the same holds for their files."""

    def _file(self, status):
        from ..models import VisitReportFile
        visit = self._visit(self.section, self.colleague)
        report = VisitReport.objects.create(
            visit_schedule=visit, status=status, meta={},
            teacher_discussion='', student_discussion='', visit_letter='')
        f = VisitReportFile(visit_report=report, uploaded_by=self.colleague)
        f.file.name = 'visit_report_files/x.pdf'
        f.save()
        return visit, f

    def _url(self, visit, f):
        return reverse('faculty_class_visit:download_file',
                       kwargs={'visit_id': visit.id, 'file_id': f.id})

    def _get(self, visit, f):
        from unittest.mock import patch
        from django.http import HttpResponse
        from ..views import faculty as faculty_views
        with patch.object(faculty_views.uploads, 'file_response',
                          return_value=HttpResponse(b'ok')):
            return self.client.get(self._url(visit, f))

    def test_colleague_cannot_download_a_file_on_a_draft(self):
        self._settings(faculty_view_others_visits='Yes')
        visit, f = self._file('Draft')
        self.client.force_login(self.me)
        self.assertEqual(self._get(visit, f).status_code, 404)

    def test_colleague_may_download_a_file_on_a_submitted_report(self):
        self._settings(faculty_view_others_visits='Yes')
        visit, f = self._file('Submitted')
        self.client.force_login(self.me)
        self.assertEqual(self._get(visit, f).status_code, 200)

    def test_visitor_may_download_a_file_on_their_own_draft(self):
        visit, f = self._file('Draft')
        self.client.force_login(self.colleague)
        self.assertEqual(self._get(visit, f).status_code, 200)


class NotYourVisitTest(_Base):
    def test_editing_someone_elses_report_explains_why(self):
        self.client.force_login(self.me)
        resp = self.client.get(reverse(
            'faculty_class_visit:edit_visit_report', kwargs={'visit_id': self.their_visit.id}))
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, 'League, Col', status_code=403)

    def test_editing_someone_elses_visit_explains_why(self):
        self.client.force_login(self.me)
        resp = self.client.get(reverse('faculty_class_visit:edit_visit', kwargs={
            'class_section_id': self.section.id, 'visit_id': self.their_visit.id}))
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, 'League, Col', status_code=403)

    def test_cannot_save_someone_elses_visit(self):
        self._settings(visit_types='Initial')
        self.client.force_login(self.me)
        resp = self.client.post(reverse('faculty_class_visit:edit_visit', kwargs={
            'class_section_id': self.section.id, 'visit_id': self.their_visit.id}), {
            'class_sections': [str(self.section.id)], 'visitors': [str(self.me.id)],
            'visit_date': '10/02/2026', 'type_of_visit': 'Initial'})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(list(self.their_visit.visitors.all()), [self.colleague])

    def test_cannot_delete_someone_elses_visit(self):
        visit = self._visit(self.section, self.colleague)
        self.client.force_login(self.me)
        resp = self.client.post(reverse(
            'faculty_class_visit:delete_visit', kwargs={'visit_id': visit.id}))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(VisitSchedule.objects.filter(pk=visit.pk).exists())

    def test_a_visitor_outside_the_course_area_can_still_edit_their_visit(self):
        # "My Observations" lists every visit the user is a visitor on, so its Edit
        # button must work even without a course role for that section.
        visit = self._visit(self.section, self.outsider)
        self.client.force_login(self.outsider)
        resp = self.client.get(reverse('faculty_class_visit:edit_visit', kwargs={
            'class_section_id': self.section.id, 'visit_id': visit.id}))
        self.assertEqual(resp.status_code, 200)
        form = resp.context['form']
        self.assertIn(str(self.section.id), {c[0] for c in form.fields['class_sections'].choices})
        self.assertIn(str(self.outsider.id), {c[0] for c in form.fields['visitors'].choices})

    def test_out_of_scope_faculty_still_gets_404(self):
        self.client.force_login(self.outsider)
        resp = self.client.get(reverse(
            'faculty_class_visit:edit_visit_report', kwargs={'visit_id': self.their_visit.id}))
        self.assertEqual(resp.status_code, 404)


class CEFacultyFilterTest(_Base):
    def test_index_offers_a_faculty_filter_of_people_who_visited(self):
        self.client.force_login(_user('ce'))
        resp = self.client.get(reverse('class_visit:ce_index'))
        self.assertEqual(resp.status_code, 200)
        names = {str(u.id) for u in resp.context['faculty']}
        self.assertTrue({str(self.me.id), str(self.colleague.id)} <= names)
        self.assertContains(resp, 'name="visitor"')

    def test_instructor_column_says_not_assigned_without_a_teacher(self):
        visit = self._visit(self.bare_a, self.me)
        self.client.force_login(_user('ce'))
        resp = self.client.get(
            f'/ce/class_visits/api/visit_schedule/?format=json&class_section_id={self.bare_a.id}')
        rows = resp.json()
        rows = rows['results'] if isinstance(rows, dict) else rows
        row = next(r for r in rows if r['id'] == str(visit.id))
        self.assertEqual(row['teacher_display'], 'Not assigned')
