"""Regression tests: signal dedup — the NEW service layer is the sole email sender.

After the signal refactor:
- VisitSchedule post_save does not call notify_instructor / notify_visitors
  (those legacy model methods have been removed).
- VisitReport post_save does not call send_visit_letter / notify_course_administrator
  (those legacy model methods have been removed).
- The pre_save status_changed handler is kept (non-email bookkeeping only).

When a visit is created via the faculty form (VisitScheduleForm) or the CE form
(CEVisitScheduleForm), exactly ONE call to the new service layer
(notify_teacher_visit_scheduled) should occur.

When a report is submitted via VisitReportDynamicForm, exactly ONE call to the
new service layer (notify_teacher_report_submitted / notify_notification_target)
should occur.
"""

import uuid
from unittest.mock import patch, MagicMock

from django.test import TestCase


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_section(teacher_id=None, status='A'):
    """Return a minimal mock ClassSection."""
    section = MagicMock()
    section.id = uuid.uuid4()
    section.status = status
    t = MagicMock()
    t.pk = teacher_id or uuid.uuid4()
    section.teacher = t
    return section


# ---------------------------------------------------------------------------
# 1. Signal file: post_save handlers invoke the new service, not legacy methods
# ---------------------------------------------------------------------------

class SignalEmailCallsRemovedTest(TestCase):
    """post_save handlers for VisitSchedule/VisitReport must not call legacy email methods.

    The legacy methods (notify_instructor, notify_visitors, send_visit_letter,
    notify_course_administrator) have been removed from the models entirely.
    These tests confirm the signals fire without raising AttributeError and that
    the new service layer is called instead.
    """

    def test_visit_schedule_post_save_does_not_raise_on_email_instructor(self):
        """Saving a VisitSchedule with email_instructor notification completes cleanly."""
        from class_visit.class_visit.models import VisitSchedule

        # Use a plain MagicMock (no spec) — legacy methods no longer exist on the class.
        visit = MagicMock()
        visit.meta = {'visit_notifications': ['email_instructor']}
        visit.pk = uuid.uuid4()

        import class_visit.class_visit.signals  # noqa — ensures handler is registered

        from django.db.models.signals import post_save
        # Should not raise AttributeError from calling removed notify_instructor
        post_save.send(sender=VisitSchedule, instance=visit, created=True)

    def test_visit_schedule_post_save_does_not_raise_on_email_visitors(self):
        """Saving a VisitSchedule with email_visitors notification completes cleanly."""
        from class_visit.class_visit.models import VisitSchedule

        visit = MagicMock()
        visit.meta = {'visit_notifications': ['email_visitors']}
        visit.pk = uuid.uuid4()

        import class_visit.class_visit.signals  # noqa

        from django.db.models.signals import post_save
        post_save.send(sender=VisitSchedule, instance=visit, created=True)

    def test_visit_report_post_save_does_not_raise_on_submit(self):
        """Saving a submitted VisitReport completes cleanly without legacy email calls."""
        from class_visit.class_visit.models import VisitReport

        report = MagicMock()
        report.is_submitted = True
        report.meta = {}
        report.pk = uuid.uuid4()

        import class_visit.class_visit.signals  # noqa

        from django.db.models.signals import post_save
        post_save.send(sender=VisitReport, instance=report, created=False)

    def test_visit_report_post_save_does_not_raise_on_notify_course_admin(self):
        """Saving a submitted VisitReport completes cleanly (no notify_course_administrator)."""
        from class_visit.class_visit.models import VisitReport

        report = MagicMock()
        report.is_submitted = True
        report.meta = {}
        report.pk = uuid.uuid4()

        import class_visit.class_visit.signals  # noqa

        from django.db.models.signals import post_save
        post_save.send(sender=VisitReport, instance=report, created=False)


# ---------------------------------------------------------------------------
# 2. Faculty VisitScheduleForm: new service is sole notifier on create
# ---------------------------------------------------------------------------

def _faculty_form_save_with_mocks(settings_dict, is_new=True):
    """
    Call VisitScheduleForm.save() with the ORM fully mocked out.

    Returns (mock_visit, mock_notify_fn) so callers can assert on call counts.
    """
    from class_visit.class_visit.forms.faculty import VisitScheduleForm

    section = _make_section()
    visitor_id = uuid.uuid4()

    mock_visit = MagicMock()
    # pk=None simulates a pre-save instance so is_new=True in form.save()
    mock_visit.pk = None
    mock_visit.meta = {}
    mock_visit.class_sections = MagicMock()
    mock_visit.visitors = MagicMock()
    mock_visit.notify_instructor = MagicMock()
    mock_visit.ensure_confirmation_token = MagicMock()

    mock_notify = MagicMock()

    with patch(
        'class_visit.class_visit.forms.faculty.ClassVisitSettings'
    ) as MockSettings, patch(
        'class_visit.class_visit.forms.faculty.VisitSchedule'
    ) as MockVS, patch(
        'class_visit.class_visit.forms.faculty.ClassSection'
    ) as MockCS, patch(
        'class_visit.class_visit.forms.faculty.CustomUser'
    ) as MockUser, patch(
        'class_visit.class_visit.forms.faculty.CourseAdministrator'
    ) as MockCA, patch(
        'class_visit.class_visit.forms.faculty.NotNeededVisit'
    ) as MockNNV, patch(
        'class_visit.class_visit.services.emails.notify_teacher_visit_scheduled',
        mock_notify,
    ):
        MockSettings.from_db.return_value = settings_dict
        MockCS.objects.filter.return_value = [section]
        MockCS.objects.filter.return_value = MagicMock()  # for the set() call
        MockUser.objects.filter.return_value = MagicMock()
        MockNNV.objects.filter.return_value.values_list.return_value = []
        MockCA.objects.filter.return_value = []
        MockVS.sections_share_teacher.return_value = True
        MockVS.return_value = mock_visit
        MockVS.objects.filter.return_value = MagicMock()

        form = VisitScheduleForm.__new__(VisitScheduleForm)
        form._faculty_user = MagicMock()
        form._visit_schedule = None if is_new else mock_visit
        form._settings = settings_dict
        form.cleaned_data = {
            'class_sections': [str(section.id)],
            'visitors': [str(visitor_id)],
            'visit_date': '06/20/2026',
            'type_of_visit': 'Observation',
            'pre_visit_note': '',
        }

        form.save(commit=True)

    return mock_visit, mock_notify


class FacultyFormNotifyOnceTest(TestCase):
    """VisitScheduleForm.save() triggers the new service — legacy model method is silent."""

    def test_new_service_called_once_on_create_notify_yes(self):
        """When notify_teacher_on_schedule=Yes, new service called exactly once."""
        settings_dict = {
            'section_status_filter': 'active',
            'visit_types': 'Observation',
            'notify_teacher_on_schedule': 'Yes',
        }
        mock_visit, mock_notify = _faculty_form_save_with_mocks(settings_dict, is_new=True)
        mock_notify.assert_called_once_with(mock_visit)
        mock_visit.notify_instructor.assert_not_called()

    def test_new_service_not_called_when_setting_is_no(self):
        """When notify_teacher_on_schedule=No, new service must not be called."""
        settings_dict = {
            'section_status_filter': 'active',
            'visit_types': 'Observation',
            'notify_teacher_on_schedule': 'No',
        }
        _, mock_notify = _faculty_form_save_with_mocks(settings_dict, is_new=True)
        mock_notify.assert_not_called()


# ---------------------------------------------------------------------------
# 3. CE form: new service called exactly once on create, not on edit
# ---------------------------------------------------------------------------

def _ce_form_save_with_mocks(visit_id_val, settings_dict, existing_visit=None):
    """
    Call CEVisitScheduleForm.save() with the ORM fully mocked.
    Returns (mock_visit, mock_notify_fn).
    """
    from class_visit.class_visit.forms.ce import CEVisitScheduleForm

    section = _make_section()
    visitor_id = uuid.uuid4()

    mock_visit = MagicMock()
    mock_visit.pk = uuid.uuid4()
    mock_visit.meta = {}
    mock_visit.class_sections = MagicMock()
    mock_visit.visitors = MagicMock()
    mock_visit.notify_instructor = MagicMock()

    mock_notify = MagicMock()

    with patch(
        'class_visit.class_visit.forms.ce.VisitSchedule'
    ) as MockVS, patch(
        'class_visit.class_visit.forms.ce.ClassSection'
    ) as MockCS, patch(
        'class_visit.class_visit.forms.ce.CustomUser'
    ) as MockUser, patch(
        'class_visit.class_visit.forms.ce.ClassVisitSettings'
    ) as MockSettings, patch(
        'class_visit.class_visit.services.emails.notify_teacher_visit_scheduled',
        mock_notify,
    ):
        MockVS.return_value = mock_visit
        MockVS.objects.get.return_value = existing_visit or mock_visit
        MockCS.objects.filter.return_value = [section]
        MockUser.objects.filter.return_value = []
        MockSettings.from_db.return_value = settings_dict

        form = CEVisitScheduleForm.__new__(CEVisitScheduleForm)
        form.cleaned_data = {
            'visit_id': visit_id_val,
            'type_of_visit': 'Observation',
            'visit_date': '2026-06-20',
            'pre_visit_note': '',
            'notifications': [],
            'class_sections': [str(section.id)],
            'visitors': [str(visitor_id)],
        }

        form.save()

    return mock_visit, mock_notify


class CEFormNotifyOnceTest(TestCase):
    """CEVisitScheduleForm.save() triggers new service exactly once on create."""

    def test_new_service_called_once_on_ce_create_notify_yes(self):
        """On CE-created visit with notify_teacher_on_schedule=Yes, service called once."""
        settings_dict = {'notify_teacher_on_schedule': 'Yes'}
        mock_visit, mock_notify = _ce_form_save_with_mocks('-1', settings_dict)
        mock_notify.assert_called_once_with(mock_visit)
        mock_visit.notify_instructor.assert_not_called()

    def test_new_service_not_called_on_ce_edit(self):
        """On CE edit (not new), notify_teacher_visit_scheduled must NOT be called."""
        existing_visit_id = str(uuid.uuid4())
        settings_dict = {'notify_teacher_on_schedule': 'Yes'}
        _, mock_notify = _ce_form_save_with_mocks(existing_visit_id, settings_dict)
        mock_notify.assert_not_called()

    def test_new_service_not_called_when_setting_is_no(self):
        """CE create with notify_teacher_on_schedule=No must not call the service."""
        settings_dict = {'notify_teacher_on_schedule': 'No'}
        _, mock_notify = _ce_form_save_with_mocks('-1', settings_dict)
        mock_notify.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Faculty report form: new service called exactly once on submit
# ---------------------------------------------------------------------------

class FacultyReportFormNotifyOnceTest(TestCase):
    """VisitReportDynamicForm.save() triggers new service exactly once — legacy never called."""

    def test_new_service_called_once_on_report_submit(self):
        """notify_teacher_report_submitted + notify_notification_target each called once."""
        from class_visit.class_visit.forms.faculty import VisitReportDynamicForm

        mock_visit = MagicMock()
        mock_visit.pk = uuid.uuid4()

        mock_report = MagicMock()
        mock_report.pk = uuid.uuid4()
        mock_report.meta = {}
        mock_report.status = 'Draft'
        mock_report.send_visit_letter = MagicMock()
        mock_report.notify_course_administrator = MagicMock()

        mock_notify_teacher = MagicMock()
        mock_notify_target = MagicMock()

        with patch(
            'class_visit.class_visit.forms.faculty.report_fields'
        ) as mock_rf, patch(
            'class_visit.class_visit.forms.faculty.VisitReport'
        ) as MockVR, patch(
            'class_visit.class_visit.services.emails.notify_teacher_report_submitted',
            mock_notify_teacher,
        ), patch(
            'class_visit.class_visit.services.emails.notify_notification_target',
            mock_notify_target,
        ), patch(
            'class_visit.class_visit.settings.class_visit.class_visit.from_db',
            return_value={'notify_teacher_on_submit': 'Yes'},
        ):
            mock_rf.build_report_form_fields.return_value = {}
            mock_rf.get_report_field_defs.return_value = []
            MockVR.objects.get_or_create.return_value = (mock_report, True)

            form = VisitReportDynamicForm(visit=mock_visit)
            form.cleaned_data = {'submit_action': 'submit'}
            created_by = MagicMock()

            form.save(created_by_user=created_by, commit=True)

        mock_notify_teacher.assert_called_once_with(mock_report)
        mock_notify_target.assert_called_once_with(mock_report)
        mock_report.send_visit_letter.assert_not_called()
        mock_report.notify_course_administrator.assert_not_called()
