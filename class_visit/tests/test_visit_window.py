"""#24: faculty schedule visits only on terms whose class-visit window (cis
Term.visit_window_opens_on / _closes_on, inherited by sub-terms) is open.
With no window on any term, or a cis without the fields, nothing changes."""
import datetime
from unittest.mock import patch

from unittest import skipUnless

from django.conf import settings as django_settings
from django.test import Client, RequestFactory
from django.urls import reverse

from cis.models.section import ClassSection
from cis.models.term import AcademicYear, Term

from . import PKG
from .test_ce_schedule_on_behalf import SETTINGS, _Fixture, _sfx
from ..forms.faculty import VisitScheduleForm
from ..models import VisitSchedule
from ..services import terms as term_service
from ..views.faculty import FacultySchedulableSectionViewSet

D = datetime.date
TODAY = D(2026, 11, 18)


@skipUnless(term_service.has_visit_window_fields(), 'cis without the visit window (< v0.2.12a)')
class _WindowFixture(_Fixture):
    """This year's term (the fixture's) and last year's, each with a section."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        old_ay = AcademicYear.objects.create(name=f'AY-old-{_sfx()}')
        cls.old_term = Term.objects.create(
            academic_year=old_ay, code='FA-old', label=f'Fall-old-{_sfx()}')
        cls.old_section = ClassSection.objects.create(
            course=cls.course, term=cls.old_term, teacher=cls.teacher,
            class_number=f'C-{_sfx()}', section_number='009', status='A')

    def setUp(self):
        for target in ('views.faculty.ClassVisitSettings.from_db',
                       'forms.faculty.ClassVisitSettings.from_db',
                       'forms.ce.ClassVisitSettings.from_db'):
            p = patch(f'{PKG}.{target}', return_value=SETTINGS)
            p.start()
            self.addCleanup(p.stop)
        p = patch('django.utils.timezone.localdate', return_value=TODAY)
        p.start()
        self.addCleanup(p.stop)

    def _windows(self):
        """This year open, last year closed."""
        Term.objects.filter(pk=self.term.pk).update(
            visit_window_opens_on=D(2026, 8, 1), visit_window_closes_on=D(2027, 6, 30))
        Term.objects.filter(pk=self.old_term.pk).update(
            visit_window_opens_on=D(2025, 8, 1), visit_window_closes_on=D(2026, 6, 30))

    def _feed(self, **params):
        vs = FacultySchedulableSectionViewSet()
        req = RequestFactory().get('/faculty/class_visits/api/class_sections/', params)
        req.user = self.faculty
        vs.request, vs.format_kwarg, vs.kwargs = req, None, {}
        return set(vs.get_queryset().values_list('pk', flat=True))

    def _form(self, visit=None, data=None):
        return VisitScheduleForm(self.faculty, visit_schedule=visit, data=data)

    def _data(self, *sections):
        return {'class_sections': [str(s.id) for s in sections],
                'visitors': [str(self.faculty.id)], 'has_other_visitors': 'No',
                'visit_date': '11/20/2026', 'type_of_visit': 'Initial'}


class WindowServiceTest(_WindowFixture):
    def test_no_window_anywhere_means_no_restriction(self):
        self.assertIsNone(term_service.open_visit_term_ids())
        self.assertEqual(term_service.closed_visit_terms([self.old_section]), [])

    def test_open_and_closed_windows(self):
        self._windows()
        ids = term_service.open_visit_term_ids()
        self.assertIn(self.term.pk, ids)
        self.assertNotIn(self.old_term.pk, ids)
        self.assertEqual(term_service.closed_visit_terms(
            [self.old_section, self.section, self.old_section]), [self.old_term])

    def test_term_without_a_window_is_closed_once_windows_are_used(self):
        Term.objects.filter(pk=self.term.pk).update(visit_window_opens_on=D(2026, 8, 1))
        ids = term_service.open_visit_term_ids()
        self.assertIn(self.term.pk, ids)        # open end: no closing date
        self.assertNotIn(self.old_term.pk, ids)

    def test_sub_term_inherits_the_parent_window(self):
        self._windows()
        sub = Term.objects.create(academic_year=self.term.academic_year, code='FA1',
                                  label=f'Fall A-{_sfx()}', parent=self.term)
        own = Term.objects.create(academic_year=self.term.academic_year, code='FA2',
                                  label=f'Fall B-{_sfx()}', parent=self.term,
                                  visit_window_closes_on=D(2026, 11, 1))
        ids = term_service.open_visit_term_ids()
        self.assertIn(sub.pk, ids)
        self.assertNotIn(own.pk, ids)           # its own close date wins

    def test_campuses_are_decided_separately(self):
        from cis.models.course import Campus
        a = Campus.objects.create(name=f'A-{_sfx()}',
                                  code=f'{django_settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        b = Campus.objects.create(name=f'B-{_sfx()}',
                                  code=f'{django_settings.CAMPUS_CODE_PREFIX}-{_sfx()}')
        AcademicYear.objects.filter(pk=self.term.academic_year_id).update(campus=a)
        AcademicYear.objects.filter(pk=self.old_term.academic_year_id).update(campus=b)
        a_next = Term.objects.create(academic_year=self.term.academic_year, code='SP',
                                     label=f'Spring-{_sfx()}')
        Term.objects.filter(pk=self.term.pk).update(visit_window_opens_on=D(2026, 8, 1))
        ids = term_service.open_visit_term_ids()
        self.assertIn(self.term.pk, ids)
        self.assertNotIn(a_next.pk, ids)        # same campus, no window: closed
        self.assertIn(self.old_term.pk, ids)    # campus B set none: still open

    def test_older_cis_without_the_fields(self):
        self._windows()
        with patch.object(term_service, 'has_visit_window_fields', return_value=False):
            self.assertIsNone(term_service.open_visit_term_ids())
            self.assertIn(self.old_section.pk, self._feed())


class FacultyFeedAndFormTest(_WindowFixture):
    def test_feed_unchanged_without_windows(self):
        self.assertTrue({self.section.pk, self.old_section.pk} <= self._feed())

    def test_feed_drops_closed_terms_even_without_term_id(self):
        self._windows()
        feed = self._feed()
        self.assertIn(self.section.pk, feed)
        self.assertNotIn(self.old_section.pk, feed)
        self.assertNotIn(self.old_section.pk, self._feed(term_id=str(self.old_term.pk)))

    def test_new_visit_offers_and_accepts_only_open_terms(self):
        self._windows()
        values = [v for v, _ in self._form().fields['class_sections'].choices]
        self.assertIn(str(self.section.id), values)
        self.assertNotIn(str(self.old_section.id), values)
        form = self._form(data=self._data(self.old_section))
        self.assertFalse(form.is_valid())
        self.assertIn('class_sections', form.errors)
        self.assertTrue(self._form(data=self._data(self.section)).is_valid())

    def test_closed_window_message_from_clean(self):
        self._windows()
        form = self._form(data=self._data(self.old_section))
        form.fields['class_sections'].choices = [(str(self.old_section.id), 'x')]
        self.assertFalse(form.is_valid())
        self.assertIn('class-visit window is closed', str(form.errors['class_sections']))

    def test_editing_a_visit_on_a_closed_term_keeps_its_section(self):
        visit = VisitSchedule.objects.create(
            visit_date=D(2026, 10, 1), type_of_visit='Initial', meta={})
        visit.class_sections.add(self.old_section)
        visit.visitors.add(self.faculty)
        self._windows()
        form = self._form(visit=visit, data=self._data(self.old_section))
        self.assertTrue(form.is_valid(), form.errors)


class FacultyPageTest(_WindowFixture):
    def setUp(self):
        super().setUp()
        self.client = Client(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.faculty)

    def _ctx(self, active=None):
        with patch(f'{PKG}.views.faculty.get_active_term', return_value=active):
            resp = self.client.get(reverse('faculty_class_visit:visits'))
        self.assertEqual(resp.status_code, 200)
        return resp.context

    def test_dropdown_lists_every_term_without_windows(self):
        ctx = self._ctx(active=self.old_term)
        ids = [tid for tid, _ in ctx['schedule_term_choices']]
        self.assertIn(str(self.old_term.pk), ids)
        self.assertEqual(ctx['schedule_term_id'], str(self.old_term.pk))

    def test_dropdown_lists_open_terms_and_skips_a_closed_active_term(self):
        self._windows()
        ctx = self._ctx(active=self.old_term)
        ids = [tid for tid, _ in ctx['schedule_term_choices']]
        self.assertIn(str(self.term.pk), ids)
        self.assertNotIn(str(self.old_term.pk), ids)
        self.assertEqual(ctx['schedule_term_id'], '')   # "All open terms"
        # The My Observations filter still lists every term.
        self.assertIn(str(self.old_term.pk), [t for t, _ in ctx['term_choices']])


class CEWarningTest(_WindowFixture):
    def setUp(self):
        super().setUp()
        self.client = Client(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.ce_user)
        self._windows()

    def test_manage_visit_warns_on_a_closed_term_and_still_saves(self):
        url = reverse('class_visit:ce_manage_visit', args=[self.old_section.id])
        html = self.client.get(url).content.decode()
        self.assertIn('data-visit-window-closed', html)
        self.assertIn(str(self.old_term), html)
        self.assertNotIn('data-visit-window-closed', self.client.get(
            reverse('class_visit:ce_manage_visit', args=[self.section.id])).content.decode())
        resp = self.client.post(url, {
            'class_sections': [str(self.old_section.id)],
            'visitors': [str(self.faculty.id)], 'visit_date': '2026-11-20',
            'type_of_visit': 'Initial', 'visit_id': '-1'})
        self.assertTrue(resp.json()['success'], resp.json())

    def test_picker_flags_closed_terms(self):
        def badges(term):
            return self.client.get(reverse('class_visit:ce_schedule_picker'), {
                'term_id': str(term.pk)}).content.decode().count('data-visit-window-closed')
        self.assertEqual(badges(self.old_term), 1)
        self.assertEqual(badges(self.term), 0)


class ErrorMessageTest(_WindowFixture):
    def test_faculty_modal_message_names_the_problem(self):
        from ..services.form_messages import error_message
        self._windows()
        form = self._form(data=self._data(self.old_section))
        form.fields['class_sections'].choices = [(str(self.old_section.id), 'x')]
        self.assertFalse(form.is_valid())
        msg = error_message(form)
        self.assertIn('Class Section(s) to Visit:', msg)
        self.assertIn('class-visit window is closed', msg)
