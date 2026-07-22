from django.test import TestCase

from class_visit.class_visit.settings.class_visit import class_visit as CVSettings
from cis.models.settings import Setting


class ClassVisitSettingsTests(TestCase):
    def test_form_has_payment_tracking_field(self):
        form = CVSettings()
        self.assertIn('payment_tracking', form.fields)

    def test_install_seeds_payment_tracking_no(self):
        CVSettings().install()
        self.assertEqual(CVSettings.from_db().get('payment_tracking'), 'No')
