"""Per-visit-type instructor emails and portal visibility (#21).

NNU's "Annual Contract" visits are internal (tracking and payment): the
instructor should get no email about them and not see them in the portal.
Each Visit Type now carries three options -- email on schedule, email on
submit, instructor can see it -- and a type the instructor can't see gets
neither email. Types with no options keep today's behaviour.
"""
import datetime
import json
import tempfile
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from cis.models.course import Cohort, Course
from cis.models.section import ClassSection
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from . import PKG
from ..models import VisitReport, VisitReportFile, VisitSchedule
from ..services import emails as email_service
from ..services import visit_types
from ..services.confirmation import confirm_visit
from ..settings.class_visit import class_visit as CVSettings
from .test_settings_class_visit import BASE_DATA

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

User = get_user_model()

HIDDEN = {'notify_on_schedule': False, 'notify_on_submit': False,
          'instructor_visible': False}


def _sfx():
    return uuid.uuid4().hex[:8]


def _cfg(options=None, **extra):
    cfg = {
        'is_active': 'No',
        'visit_types': 'Initial|Annual Contract',
        'notify_teacher_on_schedule': 'Yes',
        'notify_teacher_on_submit': 'Yes',
        'notify_office_on_submit': 'Yes',
        'notify_target': 'generic_email',
        'generic_email': 'office@example.edu',
        'instructor_confirm_link': 'Yes',
        'instructor_signature': 'Yes',
        'teacher_scheduled_subject': 'Scheduled',
        'teacher_scheduled_message': 'Hi',
        'teacher_submit_subject': 'Submitted',
        'teacher_submit_message': 'Report: {{public_report_url}}',
    }
    if options is not None:
        cfg['visit_type_options'] = json.dumps(options)
    cfg.update(extra)
    return cfg


class _Fixture(TestCase):
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

    @classmethod
    def setUpTestData(cls):
        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        course = Course.objects.create(catalog_number='101', title='A', cohort=cohort)

        cls.instructor_user = User.objects.create_user(
            username=f'ins_{_sfx()}', email=f'ins_{_sfx()}@x.com', password='x',
            first_name='Ida', last_name='Instructor')
        cls.instructor_user.groups.add(Group.objects.get_or_create(name='instructor')[0])
        cls.teacher = Teacher.objects.create(user=cls.instructor_user)
        section = ClassSection.objects.create(
            course=course, term=term, teacher=cls.teacher,
            class_number=f'C-{_sfx()}', section_number='001')

        def visit(kind):
            v = VisitSchedule.objects.create(
                visit_date=datetime.date(2026, 3, 1), type_of_visit=kind,
                meta={'confirmation_token': uuid.uuid4().hex})
            v.class_sections.add(section)
            return v

        cls.initial = visit('Initial')
        cls.internal = visit('Annual Contract')

    def _settings(self, cfg):
        patcher = patch(f'{PKG}.settings.class_visit.class_visit.from_db',
                        return_value=cfg)
        patcher.start()
        self.addCleanup(patcher.stop)


class HelperTests(TestCase):
    def test_no_options_means_everything_on(self):
        v = VisitSchedule(type_of_visit='Annual Contract')
        cfg = _cfg()
        self.assertTrue(visit_types.instructor_visible(v, cfg))
        self.assertTrue(visit_types.notify_on_schedule(v, cfg))
        self.assertTrue(visit_types.notify_on_submit(v, cfg))
        self.assertEqual(visit_types.hidden_types(cfg), [])

    def test_hidden_type_forces_both_emails_off(self):
        v = VisitSchedule(type_of_visit='Annual Contract')
        cfg = _cfg({'Annual Contract': {'instructor_visible': False}})
        self.assertFalse(visit_types.notify_on_schedule(v, cfg))
        self.assertFalse(visit_types.notify_on_submit(v, cfg))

    def test_columns_are_independent_while_visible(self):
        v = VisitSchedule(type_of_visit='Initial')
        cfg = _cfg({'Initial': {'notify_on_schedule': False}})
        self.assertFalse(visit_types.notify_on_schedule(v, cfg))
        self.assertTrue(visit_types.notify_on_submit(v, cfg))
        self.assertTrue(visit_types.instructor_visible(v, cfg))

    def test_malformed_stored_value_counts_as_no_options(self):
        v = VisitSchedule(type_of_visit='Initial')
        cfg = _cfg(visit_type_options='{not json')
        self.assertTrue(visit_types.instructor_visible(v, cfg))


class EmailTests(_Fixture):
    def _send(self, func, arg, cfg):
        with patch(f'{PKG}.services.emails._get_settings', return_value=cfg), \
             patch(f'{PKG}.services.emails.send_app_email') as mock_send:
            func(arg)
        return mock_send

    def test_scheduled_email_still_sends_without_options(self):
        sent = self._send(email_service.notify_teacher_visit_scheduled, self.internal, _cfg())
        self.assertEqual(sent.call_count, 1)

    def test_scheduled_email_skipped_for_type_turned_off(self):
        cfg = _cfg({'Annual Contract': {'notify_on_schedule': False}})
        sent = self._send(email_service.notify_teacher_visit_scheduled, self.internal, cfg)
        sent.assert_not_called()
        self.internal.refresh_from_db()
        self.assertNotIn('instructor_email_sent_on', self.internal.meta)
        # Other types still email.
        sent = self._send(email_service.notify_teacher_visit_scheduled, self.initial, cfg)
        self.assertEqual(sent.call_count, 1)

    def test_global_switch_off_wins_over_type_on(self):
        cfg = _cfg({'Initial': {'notify_on_schedule': True}},
                   notify_teacher_on_schedule='No')
        sent = self._send(email_service.notify_teacher_visit_scheduled, self.initial, cfg)
        sent.assert_not_called()

    def test_submit_email_skipped_but_office_still_notified(self):
        cfg = _cfg({'Annual Contract': HIDDEN})
        report = VisitReport.objects.create(
            visit_schedule=self.internal, status='Submitted', meta={})
        sent = self._send(email_service.notify_teacher_report_submitted, report, cfg)
        sent.assert_not_called()

        office = self._send(email_service.notify_notification_target, report, cfg)
        self.assertEqual(office.call_count, 1)
        body = office.call_args.args[1]
        ce_url = reverse('class_visit:ce_view_report', kwargs={'visit_id': self.internal.id})
        self.assertIn(ce_url, body)
        self.assertNotIn(
            reverse('instructor_class_visit:report_detail',
                    kwargs={'visit_id': self.internal.id}), body)

    def test_office_link_for_course_administrators_is_the_faculty_page(self):
        cfg = _cfg({'Annual Contract': HIDDEN}, notify_target='course_administrator')
        report = VisitReport.objects.create(
            visit_schedule=self.internal, status='Submitted', meta={})
        with patch(f'{PKG}.services.emails._get_settings', return_value=cfg):
            url = email_service.office_report_url(self.internal, cfg)
        self.assertTrue(url.endswith(reverse(
            'faculty_class_visit:view_report', kwargs={'visit_id': self.internal.id})))
        self.assertIsNotNone(report)

    def test_office_link_stays_instructor_page_for_visible_type(self):
        report = VisitReport.objects.create(
            visit_schedule=self.initial, status='Submitted', meta={})
        office = self._send(email_service.notify_notification_target, report,
                            _cfg({'Annual Contract': HIDDEN}))
        self.assertIn(
            reverse('instructor_class_visit:report_detail',
                    kwargs={'visit_id': self.initial.id}),
            office.call_args.args[1])


class InstructorPortalTests(_Fixture):
    def setUp(self):
        self.client = Client(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.instructor_user)
        for v in (self.initial, self.internal):
            VisitReport.objects.create(visit_schedule=v, status='Submitted', meta={})

    def _list_ids(self):
        resp = self.client.get(
            reverse('instructor_class_visit:visit-schedule-list') + '?format=json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        rows = data.get('results', data) if isinstance(data, dict) else data
        return {str(r['id']) for r in rows}

    def test_list_shows_both_without_options(self):
        self._settings(_cfg())
        self.assertEqual(self._list_ids(), {str(self.initial.id), str(self.internal.id)})

    def test_hidden_type_absent_from_list(self):
        self._settings(_cfg({'Annual Contract': HIDDEN}))
        self.assertEqual(self._list_ids(), {str(self.initial.id)})

    def test_hidden_type_unreachable_by_direct_url(self):
        self._settings(_cfg({'Annual Contract': HIDDEN}))
        kw = {'visit_id': self.internal.id}
        self.assertEqual(self.client.get(
            reverse('instructor_class_visit:report_detail', kwargs=kw)).status_code, 404)
        self.assertEqual(self.client.get(
            reverse('instructor_class_visit:report_pdf', kwargs=kw)).status_code, 404)
        self.assertEqual(self.client.post(
            reverse('instructor_class_visit:sign_report', kwargs=kw),
            {'instructor_signature': 'Ida'}).status_code, 404)
        self.assertEqual(
            VisitReport.objects.get(visit_schedule=self.internal).instructor_signature, '')

    def test_visible_type_still_opens(self):
        self._settings(_cfg({'Annual Contract': HIDDEN}))
        self.assertEqual(self.client.get(reverse(
            'instructor_class_visit:report_detail',
            kwargs={'visit_id': self.initial.id})).status_code, 200)

    def test_bulk_download_skips_hidden_type(self):
        self._settings(_cfg({'Annual Contract': HIDDEN}))
        with patch(f'{PKG}.views.instructor.visit_letters_pdf',
                   return_value=b'%PDF') as letters:
            self.client.post(reverse('instructor_class_visit:bulk_action'), {
                'action': 'export_pdf',
                'ids[]': [str(self.initial.id), str(self.internal.id)]})
        reports = letters.call_args.args[0]
        self.assertEqual([r.visit_schedule_id for r in reports], [self.initial.id])

    def test_file_download_follows_visibility(self):
        field = VisitReportFile._meta.get_field('file')
        patcher = patch.object(field, 'storage', FileSystemStorage(location=tempfile.mkdtemp()))
        patcher.start()
        self.addCleanup(patcher.stop)
        report = VisitReport.objects.get(visit_schedule=self.internal)
        f = VisitReportFile.objects.create(
            visit_report=report, file=SimpleUploadedFile('r.pdf', b'%PDF'),
            uploaded_by=self.instructor_user, kind=VisitReportFile.INSTRUCTOR_RESPONSE)
        url = reverse('instructor_class_visit:download_file',
                      kwargs={'visit_id': self.internal.id, 'file_id': f.id})
        with patch(f'{PKG}.settings.class_visit.class_visit.from_db', return_value=_cfg()):
            self.assertEqual(self.client.get(url).status_code, 200)
        with patch(f'{PKG}.settings.class_visit.class_visit.from_db',
                   return_value=_cfg({'Annual Contract': HIDDEN})):
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_pdf_follows_visibility(self):
        url = reverse('instructor_class_visit:report_pdf', kwargs={'visit_id': self.internal.id})
        with patch(f'{PKG}.views.instructor.visit_letter_pdf', return_value=b'%PDF'):
            with patch(f'{PKG}.settings.class_visit.class_visit.from_db', return_value=_cfg()):
                self.assertEqual(self.client.get(url).status_code, 200)
            with patch(f'{PKG}.settings.class_visit.class_visit.from_db',
                       return_value=_cfg({'Annual Contract': HIDDEN})):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_stored_as_dict_or_missing_key(self):
        cfg = _cfg()
        cfg['visit_type_options'] = {'Annual Contract': HIDDEN}
        self._settings(cfg)
        self.assertEqual(self._list_ids(), {str(self.initial.id)})

    def test_ce_report_still_opens_for_hidden_type(self):
        self._settings(_cfg({'Annual Contract': HIDDEN}))
        staff = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x', is_staff=True)
        staff.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.client.force_login(staff)
        resp = self.client.get(reverse('class_visit:ce_view_report',
                                       kwargs={'visit_id': self.internal.id}))
        self.assertEqual(resp.status_code, 200)


class SecondaryTeacherTests(_Fixture):
    def test_secondary_teacher_cannot_see_hidden_type(self):
        from cis.models.section_secondary import ClassSectionSecondaryTeacher
        from cis.models.settings import Setting
        from cis.secondary_access import CLASS_VISITS
        from cis.settings.secondary_teacher_access import secondary_teacher_access
        Setting.objects.update_or_create(
            key=secondary_teacher_access.key, defaults={'value': {CLASS_VISITS: 'Yes'}})
        user = User.objects.create_user(
            username=f's_{_sfx()}', email=f's_{_sfx()}@x.com', password='x')
        user.groups.add(Group.objects.get_or_create(name='instructor')[0])
        second = Teacher.objects.create(user=user)
        ClassSectionSecondaryTeacher.objects.create(
            class_section=self.internal.class_sections.first(), teacher=second)
        self._settings(_cfg({'Annual Contract': HIDDEN}))
        client = Client(REMOTE_ADDR='127.0.0.1')
        client.force_login(user)
        rows = client.get(reverse('instructor_class_visit:visit-schedule-list'),
                          {'format': 'json'}).json()
        rows = rows['results'] if isinstance(rows, dict) else rows
        self.assertEqual({r['id'] for r in rows}, {str(self.initial.id)})


class ConfirmationLinkTests(_Fixture):
    def test_link_for_hidden_type_is_invalid(self):
        self._settings(_cfg({'Annual Contract': HIDDEN}))
        self.assertIsNone(confirm_visit(self.internal.meta['confirmation_token']))
        self.internal.refresh_from_db()
        self.assertNotIn('confirmed_on', self.internal.meta)

    def test_link_for_visible_type_confirms(self):
        self._settings(_cfg({'Annual Contract': HIDDEN}))
        self.assertEqual(confirm_visit(self.initial.meta['confirmation_token']), self.initial)


class SettingsValidationTests(TestCase):
    def _form(self, options, visit_types_value='Initial|Annual Contract'):
        data = dict(BASE_DATA, visit_types=visit_types_value,
                    visit_type_options=options)
        return CVSettings(data=data)

    def test_blank_is_valid_and_stored_as_empty_object(self):
        form = self._form('')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['visit_type_options'], '{}')

    def test_valid_options_saved(self):
        form = self._form(json.dumps({'Annual Contract': HIDDEN}))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(json.loads(form.cleaned_data['visit_type_options']),
                         {'Annual Contract': HIDDEN})

    def test_unknown_type_rejected(self):
        form = self._form(json.dumps({'Anual Contract': HIDDEN}))
        self.assertFalse(form.is_valid())
        self.assertIn('Anual Contract', str(form.errors['visit_type_options']))

    def test_unknown_option_and_non_boolean_rejected(self):
        self.assertFalse(self._form(json.dumps({'Initial': {'hide': True}})).is_valid())
        self.assertFalse(self._form(json.dumps({'Initial': {'notify_on_submit': 'No'}})).is_valid())
        self.assertFalse(self._form('[1]').is_valid())
        self.assertFalse(self._form('{bad').is_valid())

    def test_unknown_type_checked_against_cleaned_visit_types(self):
        form = self._form(json.dumps({'B': HIDDEN}), visit_types_value='A')
        self.assertFalse(form.is_valid())

    def test_retired_type_still_used_by_visits_is_accepted(self):
        VisitSchedule.objects.create(
            visit_date=datetime.date(2026, 3, 1), type_of_visit='Old Internal', meta={})
        form = self._form(json.dumps({'Old Internal': HIDDEN}))
        self.assertTrue(form.is_valid(), form.errors)

    def test_install_seeds_empty_options(self):
        from cis.models.settings import Setting
        Setting.objects.filter(key='class_visit').delete()
        CVSettings().install()
        self.assertEqual(CVSettings.from_db().get('visit_type_options'), '{}')
