from django.test import TestCase

from class_visit.class_visit.settings.class_visit import class_visit as CVSettings
from cis.models.settings import Setting


# A complete, valid POST payload for the settings form; individual tests
# override `report_fields_json` / `visit_types` to exercise the validator.
BASE_DATA = {
    'is_active': 'No',
    'debug_email_list': '',
    'payment_tracking': 'No',
    'visit_types': 'Initial|Follow-up|Annual',
    'report_fields_json': '[]',
    'section_status_filter': 'active',
    'notify_target': 'course_administrator',
    'generic_email': '',
    'notify_teacher_on_schedule': 'No',
    'teacher_scheduled_subject': '',
    'teacher_scheduled_message': '',
    'instructor_confirm_link': 'No',
    'notify_teacher_on_submit': 'No',
    'teacher_submit_subject': '',
    'teacher_submit_message': '',
    'visitor_reminder_subject': '',
    'visitor_reminder_message': '',
    'reminder_every_days': '7',
}


def _form(report_fields_json, **overrides):
    data = dict(BASE_DATA)
    data['report_fields_json'] = report_fields_json
    data.update(overrides)
    return CVSettings(data=data)


class ClassVisitSettingsTests(TestCase):
    def test_form_has_payment_tracking_field(self):
        form = CVSettings()
        self.assertIn('payment_tracking', form.fields)

    def test_install_seeds_payment_tracking_no(self):
        CVSettings().install()
        self.assertEqual(CVSettings.from_db().get('payment_tracking'), 'No')


class ReportFieldsJsonValidatorTests(TestCase):
    def test_empty_and_blank_are_valid(self):
        self.assertTrue(_form('[]').is_valid())
        self.assertTrue(_form('').is_valid())

    def test_valid_config_passes(self):
        good = (
            '[{"name":"field_initial","label":"Label 1","type":"select",'
            '"public":true,"required":false,"options":["A","B"],"visit_types":["Initial"]}]'
        )
        form = _form(good)
        self.assertTrue(form.is_valid(), form.errors)

    def test_invalid_json_rejected(self):
        # The exact malformed payload a user hit: `"label":"Label" 2`.
        bad = '[{"name":"f","label":"Label" 2,"type":"select","options":["A"]}]'
        form = _form(bad)
        self.assertFalse(form.is_valid())
        self.assertIn('report_fields_json', form.errors)

    def test_non_list_rejected(self):
        form = _form('{"name":"f","label":"L","type":"text"}')
        self.assertFalse(form.is_valid())
        self.assertIn('report_fields_json', form.errors)

    def test_missing_required_key_rejected(self):
        form = _form('[{"label":"L","type":"text"}]')  # no name
        self.assertFalse(form.is_valid())
        self.assertIn('report_fields_json', form.errors)

    def test_bad_type_rejected(self):
        form = _form('[{"name":"f","label":"L","type":"bogus"}]')
        self.assertFalse(form.is_valid())
        self.assertIn('report_fields_json', form.errors)

    def test_select_without_options_rejected(self):
        form = _form('[{"name":"f","label":"L","type":"select"}]')
        self.assertFalse(form.is_valid())
        self.assertIn('report_fields_json', form.errors)

    def test_duplicate_name_rejected(self):
        dup = (
            '[{"name":"f","label":"L1","type":"text"},'
            '{"name":"f","label":"L2","type":"text"}]'
        )
        form = _form(dup)
        self.assertFalse(form.is_valid())
        self.assertIn('report_fields_json', form.errors)

    def test_visit_types_not_a_list_rejected(self):
        form = _form('[{"name":"f","label":"L","type":"text","visit_types":"Initial"}]')
        self.assertFalse(form.is_valid())
        self.assertIn('report_fields_json', form.errors)

    def test_unknown_visit_type_rejected(self):
        # "Followup" is not in the configured Visit Types (Initial|Follow-up|Annual).
        form = _form('[{"name":"f","label":"L","type":"text","visit_types":["Followup"]}]')
        self.assertFalse(form.is_valid())
        self.assertIn('report_fields_json', form.errors)

    def test_known_visit_type_passes(self):
        form = _form('[{"name":"f","label":"L","type":"text","visit_types":["Follow-up"]}]')
        self.assertTrue(form.is_valid(), form.errors)
