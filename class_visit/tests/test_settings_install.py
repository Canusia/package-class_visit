"""install() seeds missing keys; it must never overwrite a configured tenant (#10).

The old body did `setting.value = defaults` unconditionally, on the existing row as well
as a new one. `register_settings` calls install() whenever no SettingRecord named
`class_visit` exists — a state a container can reach with the Setting row still populated
— so an ordinary boot could replace a tenant's entire Class Visit configuration (report
fields, every email body, visit types) with defaults. No error, no warning, exit code 0.
Hit for real on ewu.

Seeding must therefore be additive, and a complete row must be left alone entirely.
"""
from django.http import HttpRequest
from django.test import TestCase

from cis.models.settings import Setting

from ..settings.class_visit import class_visit as CVSettings


CONFIGURED = {
    'is_active': 'Yes',
    'report_fields_json': '[{"name": "summary", "label": "Summary", "type": "textarea"}]',
    'visit_types': 'Site Visit|Follow-up',
    'teacher_submit_message': 'Dear {{teacher_first_name}}, your visit is complete.',
    'teacher_submit_subject': 'Your EWU site visit',
}


class InstallIsSeedOnlyTests(TestCase):
    def _install(self):
        CVSettings(HttpRequest()).install()

    def _value(self):
        return Setting.objects.get(key=CVSettings.key).value

    def test_creates_the_row_with_defaults_when_absent(self):
        Setting.objects.filter(key=CVSettings.key).delete()

        self._install()

        value = self._value()
        self.assertEqual(value['visit_types'], 'Initial|Follow-up|Annual')
        self.assertEqual(value['report_fields_json'], '[]')
        self.assertIn('reminder_every_days', value)

    def test_never_overwrites_configured_values(self):
        Setting.objects.update_or_create(
            key=CVSettings.key, defaults={'value': dict(CONFIGURED)})

        self._install()

        value = self._value()
        for key, configured in CONFIGURED.items():
            self.assertEqual(value[key], configured, msg=key)

    def test_a_deliberately_blanked_value_is_not_re_defaulted(self):
        # '' and 'No' are real choices, not "unset".
        Setting.objects.update_or_create(key=CVSettings.key, defaults={'value': {
            'teacher_submit_subject': '',
            'visit_types': '',
        }})

        self._install()

        value = self._value()
        self.assertEqual(value['teacher_submit_subject'], '')
        self.assertEqual(value['visit_types'], '')

    def test_missing_keys_are_added_without_touching_the_rest(self):
        Setting.objects.update_or_create(
            key=CVSettings.key, defaults={'value': {'visit_types': 'Site Visit'}})

        self._install()

        value = self._value()
        self.assertEqual(value['visit_types'], 'Site Visit')
        self.assertEqual(value['report_fields_json'], '[]')   # newly seeded

    def test_second_install_on_a_complete_row_writes_nothing(self):
        Setting.objects.filter(key=CVSettings.key).delete()
        self._install()
        before = Setting.objects.get(key=CVSettings.key)

        with self.assertNumQueries(1):   # the lookup only; no UPDATE
            self._install()

        after = Setting.objects.get(key=CVSettings.key)
        self.assertEqual(after.value, before.value)

    def test_a_legacy_non_dict_value_does_not_raise(self):
        # The column is NOT NULL, so the degenerate case is a non-dict JSON
        # value (a string left by an old migration), not null.
        Setting.objects.update_or_create(
            key=CVSettings.key, defaults={'value': 'legacy-string'})

        self._install()

        value = self._value()
        self.assertIsInstance(value, dict)
        self.assertEqual(value['visit_types'], 'Initial|Follow-up|Annual')
