"""Secondary teachers on a class section (cis#154).

Teacher t2 is a secondary teacher on t1's section. t2 sees and gets the
emails for its class visits only when the Secondary Teacher Access setting
allows CLASS_VISITS (default No). t1 (primary) is unchanged, and
VisitSchedule.teacher stays the primary.
"""
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import RequestFactory, TestCase
from django.urls import reverse

from cis.models.course import Cohort, Course
from cis.models.section import ClassSection
from cis.models.settings import Setting
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from . import PKG
from ..models import VisitReport, VisitSchedule

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class _Fixture(TestCase):
    def setUp(self):
        self._saved = list(user_logged_in.receivers)
        user_logged_in.receivers = []
        self.addCleanup(setattr, user_logged_in, 'receivers', self._saved)

        group = Group.objects.get_or_create(name='instructor')[0]

        def teacher(slug):
            u = User.objects.create_user(
                username=f'{slug}_{_sfx()}', email=f'{slug}_{_sfx()}@x.com',
                password='x', first_name=slug.title(), last_name='Teach')
            u.groups.add(group)
            return Teacher.objects.create(user=u)
        self.t1, self.t2, self.t3 = teacher('t1'), teacher('t2'), teacher('t3')

        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        course = Course.objects.create(catalog_number='101', title='A', cohort=cohort)
        self.section = ClassSection.objects.create(
            class_number=_sfx(), term=term, course=course, teacher=self.t1, status='A')
        self.section2 = ClassSection.objects.create(
            class_number=_sfx(), term=term, course=course, teacher=self.t1, status='A')
        from cis.models.section_secondary import ClassSectionSecondaryTeacher
        for s in (self.section, self.section2):
            ClassSectionSecondaryTeacher.objects.create(class_section=s, teacher=self.t2)

        self.visit = VisitSchedule.objects.create()
        self.visit.class_sections.set([self.section, self.section2])

    def _allow(self, value='Yes'):
        from cis.secondary_access import CLASS_VISITS
        from cis.settings.secondary_teacher_access import secondary_teacher_access
        Setting.objects.update_or_create(
            key=secondary_teacher_access.key,
            defaults={'value': {CLASS_VISITS: value}})


class InstructorScopeTests(_Fixture):
    def _feed_ids(self, teacher):
        self.client.force_login(teacher.user)
        resp = self.client.get(
            reverse('instructor_class_visit:visit-schedule-list'), {'format': 'json'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        rows = data['results'] if isinstance(data, dict) else data
        return [r['id'] for r in rows]

    def test_secondary_sees_nothing_by_default(self):
        self.assertEqual(self._feed_ids(self.t2), [])
        self.assertEqual(self._feed_ids(self.t1), [str(self.visit.id)])

    def test_secondary_sees_the_visit_once_when_allowed(self):
        self._allow()
        # Two of the visit's sections list t2: still one row.
        self.assertEqual(self._feed_ids(self.t2), [str(self.visit.id)])
        self.assertEqual(self._feed_ids(self.t3), [])

    def test_report_detail_follows_the_setting(self):
        url = reverse('instructor_class_visit:report_detail',
                      kwargs={'visit_id': self.visit.id})
        self.client.force_login(self.t2.user)
        with patch(f'{PKG}.views.instructor.draw_menu', return_value=''):
            self.assertEqual(self.client.get(url).status_code, 404)
            self._allow()
            self.assertEqual(self.client.get(url).status_code, 200)


class CETeacherFilterTests(_Fixture):
    def test_teacher_filter_matches_secondaries(self):
        from ..views.ce import CEVisitScheduleViewSet
        request = RequestFactory().get('/', {'teacher_id': str(self.t2.id)})
        view = CEVisitScheduleViewSet()
        view.request = request
        view.format_kwarg = None
        view.kwargs = {}
        self.assertEqual(list(view.get_queryset()), [self.visit])


class RecipientTests(_Fixture):
    def test_instructor_emails_primary_only_by_default(self):
        self.assertEqual(self.visit.instructor_emails, [self.t1.user.email])

    def test_instructor_emails_add_allowed_secondaries_once(self):
        self._allow()
        self.assertEqual(self.visit.instructor_emails,
                         [self.t1.user.email, self.t2.user.email])

    def test_teacher_stays_the_primary(self):
        self._allow()
        self.assertEqual(self.visit.teacher, self.t1)

    @patch(f'{PKG}.services.emails.send_app_email')
    def test_scheduled_and_submitted_emails_reach_secondaries(self, send):
        from ..services import emails
        self._allow()
        cfg = {'notify_teacher_on_schedule': 'Yes', 'notify_teacher_on_submit': 'Yes'}
        with patch(f'{PKG}.services.emails._get_settings', return_value=cfg):
            emails.notify_teacher_visit_scheduled(self.visit)
            report = VisitReport(visit_schedule=self.visit)
            emails.notify_teacher_report_submitted(report)
        self.assertEqual(send.call_count, 2)
        for call in send.call_args_list:
            self.assertEqual(call.args[2], [self.t1.user.email, self.t2.user.email])


class OlderCisFallbackTests(_Fixture):
    def test_primary_only_without_secondary_access(self):
        from .. import compat
        self._allow()
        real = compat.has_module
        with patch.object(compat, 'has_module',
                          side_effect=lambda n: False if n.startswith('cis.secondary')
                          or n == 'cis.models.section_secondary' else real(n)):
            self.assertEqual(self.visit.instructor_emails, [self.t1.user.email])
            self.assertFalse(VisitSchedule.objects.filter(
                compat.teacher_visits_q(self.t2)).exists())


class SignOffAndFilesTests(_Fixture):
    """A secondary teacher may read a visit's report and files (CLASS_VISITS)
    but only a primary teacher signs off (product call, cis#154)."""

    def setUp(self):
        super().setUp()
        import tempfile
        from django.core.files.base import ContentFile
        from django.core.files.storage import FileSystemStorage
        from ..models import VisitReportFile

        field = VisitReportFile._meta.get_field('file')
        patcher = patch.object(
            field, 'storage', FileSystemStorage(location=tempfile.mkdtemp()))
        patcher.start()
        self.addCleanup(patcher.stop)

        patcher = patch(f'{PKG}.settings.class_visit.class_visit.from_db',
                        return_value={'instructor_signature': 'Yes',
                                      'instructor_view_visitor_files': 'Yes'})
        patcher.start()
        self.addCleanup(patcher.stop)

        self.report = VisitReport.objects.create(
            visit_schedule=self.visit, status='Submitted', meta={})
        self.file = VisitReportFile(
            visit_report=self.report, kind=VisitReportFile.INSTRUCTOR_RESPONSE,
            uploaded_by=self.t1.user)
        self.file.file.save('notes.pdf', ContentFile(b'data'), save=True)

    def _sign(self, teacher):
        self.client.force_login(teacher.user)
        return self.client.post(
            reverse('instructor_class_visit:sign_report',
                    kwargs={'visit_id': self.visit.id}),
            {'instructor_signature': teacher.user.first_name,
             'instructor_response': 'noted'})

    def test_secondary_cannot_sign_even_when_allowed(self):
        self._allow()
        self.assertEqual(self._sign(self.t2).status_code, 404)
        self.report.refresh_from_db()
        self.assertFalse(self.report.instructor_signature)
        self.assertFalse(self.report.instructor_response)

    def test_primary_signs(self):
        self._allow()
        self.assertEqual(self._sign(self.t1).status_code, 302)
        self.report.refresh_from_db()
        self.assertEqual(self.report.instructor_signature, 'T1')

    def test_signoff_panel_hidden_for_secondary(self):
        self._allow()
        url = reverse('instructor_class_visit:report_detail',
                      kwargs={'visit_id': self.visit.id})
        with patch(f'{PKG}.views.instructor.draw_menu', return_value=''):
            self.client.force_login(self.t2.user)
            self.assertFalse(self.client.get(url).context['show_signoff'])
            self.client.force_login(self.t1.user)
            self.assertTrue(self.client.get(url).context['show_signoff'])

    def _download(self, teacher):
        self.client.force_login(teacher.user)
        return self.client.get(reverse(
            'instructor_class_visit:download_file',
            kwargs={'visit_id': self.visit.id, 'file_id': self.file.id}))

    def test_secondary_download_follows_the_setting(self):
        self.assertEqual(self._download(self.t2).status_code, 404)
        self._allow()
        self.assertEqual(self._download(self.t2).status_code, 200)
        self.assertEqual(self._download(self.t3).status_code, 404)
