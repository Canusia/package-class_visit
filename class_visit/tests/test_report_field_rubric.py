"""Report fields can express a rubric: heading, help_text, rating groups (#6).

A rubric used to render as N unrelated dropdowns with no section titles, no
instructions, and no visible shared scale. Three additions fix that without a
rubric engine:

- ``heading`` is layout only -- no form field, no meta key;
- ``help_text`` on any def reaches the form, never the letter;
- ``rating`` groups criteria on one scale, one meta key per criterion.

The guarantee worth most: a config using none of them behaves exactly as before.
"""
import json
import uuid
from unittest.mock import patch

from django import forms
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from ..models import VisitReport, VisitSchedule
from ..services import report_fields as rf
from .test_settings_class_visit import _form as _settings_form

User = get_user_model()

SCALE = ['Excellent', 'Adequate', 'Needs Improvement', 'N/A']

LEGACY_DEFS = [
    {'name': 'notes', 'label': 'Notes', 'type': 'textarea', 'public': True},
    {'name': 'grade', 'label': 'Grade', 'type': 'select', 'options': ['A', 'B'],
     'public': False, 'required': True},
    {'name': 'ok', 'label': 'OK', 'type': 'checkbox', 'public': True},
]

RUBRIC_DEFS = [
    {'type': 'heading', 'name': 'sec_teaching', 'label': 'Teaching',
     'help_text': 'Score each criterion.'},
    {'type': 'rating', 'name': 'teaching', 'label': 'Teaching', 'scale': SCALE,
     'public': True, 'required': True,
     'criteria': [
         {'name': 'pacing', 'label': 'Lesson pacing', 'help_text': 'Is time used well?'},
         {'name': 'questioning', 'label': 'Questioning', 'public': False},
     ]},
    {'type': 'heading', 'name': 'sec_private', 'label': 'Internal'},
    {'name': 'internal_notes', 'label': 'Internal notes', 'type': 'text',
     'public': False, 'help_text': 'Not shared with the instructor.'},
]


def _settings(defs):
    return patch.object(
        rf, '_get_settings', return_value={'report_fields_json': json.dumps(defs)})


class _Report:
    """Stand-in for VisitReport where only meta and the visit type matter."""

    def __init__(self, meta, type_of_visit=None):
        self.meta = meta
        self.visit_schedule = type('V', (), {'type_of_visit': type_of_visit})()


class CompatibilityTest(SimpleTestCase):
    """1. A config with no new types is unchanged in form fields and display."""

    def test_form_fields_are_unchanged(self):
        with _settings(LEGACY_DEFS):
            fields = rf.build_report_form_fields()

        self.assertEqual(list(fields), ['notes', 'grade', 'ok'])
        self.assertIsInstance(fields['notes'].widget, forms.Textarea)
        self.assertEqual(fields['grade'].choices, [('A', 'A'), ('B', 'B')])
        self.assertTrue(fields['grade'].required)
        for field in fields.values():
            self.assertEqual(field.help_text, '')

    def test_display_rows_have_the_old_shape(self):
        report = _Report({'notes': 'n', 'grade': 'A', 'ok': True})
        with _settings(LEGACY_DEFS):
            rows = rf.report_values_for_display(report)
            public = rf.report_values_for_display(report, public_only=True)

        self.assertEqual(rows, [
            {'label': 'Notes', 'value': 'n'},
            {'label': 'Grade', 'value': 'A'},
            {'label': 'OK', 'value': True},
        ])
        self.assertEqual(public, [
            {'label': 'Notes', 'value': 'n'},
            {'label': 'OK', 'value': True},
        ])


class HeadingTest(SimpleTestCase):
    """2. A heading produces no form field and no stored key."""

    def test_heading_produces_no_form_field(self):
        with _settings(RUBRIC_DEFS):
            fields = rf.build_report_form_fields()

        self.assertNotIn('sec_teaching', fields)
        self.assertNotIn('sec_private', fields)
        self.assertNotIn('teaching', fields)  # the group name stores nothing either

    def test_heading_is_not_an_input_def(self):
        names = [d['name'] for d in rf.input_field_defs(RUBRIC_DEFS)]
        self.assertEqual(names, ['pacing', 'questioning', 'internal_notes'])


class RatingFormTest(SimpleTestCase):
    """3 & 4. help_text reaches the form; a rating is one ChoiceField per criterion."""

    def test_one_radio_choice_field_per_criterion_over_the_scale(self):
        with _settings(RUBRIC_DEFS):
            fields = rf.build_report_form_fields()

        for name in ('pacing', 'questioning'):
            with self.subTest(name=name):
                self.assertIsInstance(fields[name], forms.ChoiceField)
                self.assertIsInstance(fields[name].widget, forms.RadioSelect)
                self.assertEqual([c for c, _ in fields[name].choices], SCALE)
                self.assertTrue(fields[name].required)

    def test_help_text_reaches_the_form_field(self):
        with _settings(RUBRIC_DEFS):
            fields = rf.build_report_form_fields()

        self.assertEqual(fields['pacing'].help_text, 'Is time used well?')
        self.assertEqual(fields['internal_notes'].help_text, 'Not shared with the instructor.')

    def test_criterion_required_overrides_the_group(self):
        defs = json.loads(json.dumps(RUBRIC_DEFS))
        defs[1]['criteria'][1]['required'] = False
        with _settings(defs):
            fields = rf.build_report_form_fields()

        self.assertTrue(fields['pacing'].required)
        self.assertFalse(fields['questioning'].required)

    def test_visit_types_on_a_group_filters_every_criterion(self):
        """7."""
        defs = json.loads(json.dumps(RUBRIC_DEFS))
        defs[1]['visit_types'] = ['Initial']
        with _settings(defs):
            initial = rf.build_report_form_fields(type_of_visit='Initial')
            annual = rf.build_report_form_fields(type_of_visit='Annual')

        self.assertIn('pacing', initial)
        self.assertNotIn('pacing', annual)
        self.assertNotIn('questioning', annual)
        self.assertIn('internal_notes', annual)


class DisplayTest(SimpleTestCase):
    """9 & 10. Letters and report pages: sections, grids, public filtering, legacy meta."""

    def test_full_display_has_headings_and_a_rating_group_without_help_text(self):
        report = _Report({'pacing': 'Excellent', 'questioning': 'Adequate',
                          'internal_notes': 'x'})
        with _settings(RUBRIC_DEFS):
            rows = rf.report_values_for_display(report)

        self.assertEqual(rows, [
            {'kind': 'heading', 'label': 'Teaching'},
            {'kind': 'rating', 'label': 'Teaching', 'scale': SCALE, 'criteria': [
                {'label': 'Lesson pacing', 'value': 'Excellent'},
                {'label': 'Questioning', 'value': 'Adequate'},
            ]},
            {'kind': 'heading', 'label': 'Internal'},
            {'label': 'Internal notes', 'value': 'x'},
        ])

    def test_public_display_drops_non_public_criteria_and_empty_headings(self):
        report = _Report({'pacing': 'Excellent', 'questioning': 'Adequate',
                          'internal_notes': 'x'})
        with _settings(RUBRIC_DEFS):
            rows = rf.report_values_for_display(report, public_only=True)

        self.assertEqual(rows, [
            {'kind': 'heading', 'label': 'Teaching'},
            {'kind': 'rating', 'label': 'Teaching', 'scale': SCALE, 'criteria': [
                {'label': 'Lesson pacing', 'value': 'Excellent'},
            ]},
        ])

    def test_legacy_meta_without_rubric_keys_renders_blank(self):
        with _settings(RUBRIC_DEFS):
            rows = rf.report_values_for_display(_Report({}))

        rating = rows[1]
        self.assertEqual([c['value'] for c in rating['criteria']], ['', ''])

    def test_letter_renders_sections_and_a_grid(self):
        report = _Report({'pacing': 'Adequate', 'questioning': 'Legacy value'})
        with _settings(RUBRIC_DEFS):
            rows = rf.report_values_for_display(report)
        html = render_to_string('class_visit/letter_body.html', {'rows': rows, 'signoff': {}})

        self.assertIn('colspan="2"', html)
        for choice in SCALE:
            self.assertIn(f'>{choice}</th>', html)
        self.assertEqual(html.count('<strong>X</strong>'), 1)
        self.assertIn('Questioning (Legacy value)', html)
        self.assertNotIn('Is time used well?', html)
        self.assertNotIn('Score each criterion.', html)

    def test_legacy_letter_has_no_rubric_markup(self):
        with _settings(LEGACY_DEFS):
            rows = rf.report_values_for_display(_Report({'notes': 'n'}))
        html = render_to_string('class_visit/letter_body.html', {'rows': rows, 'signoff': {}})

        self.assertNotIn('colspan', html)
        self.assertIn('>Notes</th>', html)


class RubricValidationTest(TestCase):
    """5 & 6. The settings form rejects malformed rubric definitions by name."""

    def _errors(self, defs):
        form = _settings_form(json.dumps(defs))
        self.assertFalse(form.is_valid())
        return ' '.join(form.errors['report_fields_json'])

    def _rating(self, **overrides):
        defn = {'type': 'rating', 'name': 'teaching', 'label': 'Teaching',
                'scale': list(SCALE),
                'criteria': [{'name': 'pacing', 'label': 'Pacing'}]}
        defn.update(overrides)
        return defn

    def test_a_valid_rubric_is_accepted(self):
        form = _settings_form(json.dumps(RUBRIC_DEFS))
        self.assertTrue(form.is_valid(), form.errors)

    def test_criterion_name_colliding_with_another_field_is_rejected(self):
        errors = self._errors([
            {'name': 'pacing', 'label': 'Pacing notes', 'type': 'text'},
            self._rating(),
        ])
        self.assertIn('Duplicate field name "pacing"', errors)

    def test_criterion_names_collide_across_groups(self):
        errors = self._errors([self._rating(), self._rating(name='other')])
        self.assertIn('Duplicate field name "pacing"', errors)

    def test_bad_scales_are_rejected_naming_the_field(self):
        for scale in ([], 'Excellent|Adequate', ['A', ''], [1, 2]):
            with self.subTest(scale=scale):
                errors = self._errors([self._rating(scale=scale)])
                self.assertIn('Field "teaching"', errors)
                self.assertIn('"scale"', errors)

    def test_duplicate_scale_values_are_rejected(self):
        errors = self._errors([self._rating(scale=['A', 'A'])])
        self.assertIn('duplicate', errors)

    def test_options_on_a_rating_is_rejected(self):
        errors = self._errors([self._rating(options=['A'])])
        self.assertIn('uses "scale", not "options"', errors)

    def test_criteria_must_be_a_non_empty_list_of_named_objects(self):
        for criteria in ([], None, ['pacing'], [{'label': 'Pacing'}], [{'name': 'pacing'}]):
            with self.subTest(criteria=criteria):
                self.assertIn('riterion' if criteria else '"criteria"',
                              self._errors([self._rating(criteria=criteria)]))

    def test_help_text_must_be_a_string(self):
        errors = self._errors([{'name': 'n', 'label': 'N', 'type': 'text', 'help_text': 3}])
        self.assertIn('"help_text" must be a string', errors)

    def test_heading_needs_no_options(self):
        form = _settings_form(json.dumps(
            [{'type': 'heading', 'name': 'sec', 'label': 'Section'}]))
        self.assertTrue(form.is_valid(), form.errors)


def _sfx():
    return uuid.uuid4().hex[:8]


class RubricSaveTest(TestCase):
    """2, 4 & 8 end to end: what the form stores, and draft vs submit."""

    def setUp(self):
        self.user = User.objects.create_user(
            username=f'fac_{_sfx()}', email=f'fac_{_sfx()}@x.com', password='x')
        self.visit = VisitSchedule.objects.create(
            visit_date=timezone.now(), type_of_visit='Observation')

    def _form(self, data):
        from ..forms.faculty import VisitReportDynamicForm
        return VisitReportDynamicForm(visit=self.visit, data=data)

    def test_submit_writes_one_meta_key_per_criterion_and_none_for_headings(self):
        with _settings(RUBRIC_DEFS):
            form = self._form({
                'submit_action': 'submit', 'pacing': 'Excellent',
                'questioning': 'N/A', 'internal_notes': 'x',
                'sec_teaching': 'phantom', 'teaching': 'phantom',
            })
            self.assertTrue(form.is_valid(), form.errors)
            report = form.save(created_by_user=self.user)

        report.refresh_from_db()
        self.assertEqual(report.meta['pacing'], 'Excellent')
        self.assertEqual(report.meta['questioning'], 'N/A')
        for phantom in ('sec_teaching', 'sec_private', 'teaching'):
            self.assertNotIn(phantom, report.meta)

    def test_draft_with_blank_criteria_saves(self):
        with _settings(RUBRIC_DEFS):
            form = self._form({'submit_action': 'draft', 'pacing': 'Adequate'})
            self.assertTrue(form.is_valid(), form.errors)
            report = form.save(created_by_user=self.user)

        self.assertEqual(report.status, 'Draft')
        self.assertEqual(report.meta['questioning'], '')

    def test_submit_with_a_blank_required_criterion_fails(self):
        with _settings(RUBRIC_DEFS):
            form = self._form({'submit_action': 'submit', 'pacing': 'Adequate'})
            self.assertFalse(form.is_valid())
        self.assertIn('questioning', form.errors)

    def test_a_value_outside_the_scale_is_rejected(self):
        with _settings(RUBRIC_DEFS):
            form = self._form({'submit_action': 'draft', 'pacing': 'Superb'})
            self.assertFalse(form.is_valid())
        self.assertIn('pacing', form.errors)

    def test_form_page_renders_a_grid_with_the_saved_choice_checked(self):
        with _settings(RUBRIC_DEFS):
            from ..forms.faculty import VisitReportDynamicForm
            form = VisitReportDynamicForm(
                visit=self.visit, initial_meta={'pacing': 'Adequate'})
            html = render_to_string(
                'class_visit/faculty/_report_form_fields.html',
                {'form': form, 'report_layout': rf.form_layout(form, 'Observation')})

        self.assertIn('cv-rating', html)
        self.assertIn('<h5', html)
        self.assertIn('Score each criterion.', html)
        self.assertIn('Is time used well?', html)
        self.assertEqual(html.count('name="pacing"'), len(SCALE))
        self.assertRegex(html, r'value="Adequate"\s+id="[^"]+"\s+aria-label="Lesson pacing: Adequate"\s+checked')
        self.assertIn('name="internal_notes"', html)
        self.assertIn('name="submit_action"', html)
        self.assertEqual(html.count('name="submit_action"'), 1)

    def test_a_field_named_like_a_template_attribute_still_renders(self):
        """A form field no def placed is appended, never dropped."""
        from ..forms.faculty import VisitReportDynamicForm
        with _settings(LEGACY_DEFS):
            form = VisitReportDynamicForm(visit=self.visit)
        form.fields['extra'] = forms.CharField(label='Extra')
        with _settings(LEGACY_DEFS):
            names = [item['field'].name for item in rf.form_layout(form)]

        self.assertEqual(names, ['notes', 'grade', 'ok', 'extra'])


class ExportTest(SimpleTestCase):
    """The CSV export: a column per criterion, none for headings."""

    def test_headers_flatten_rating_groups(self):
        from ..reports import visit_reports as vr
        # Payment columns (#17) read the DB setting; this test is about rubric headers.
        with _settings(RUBRIC_DEFS), \
                patch.object(vr, 'payment_tracking_enabled', return_value=False):
            headers = vr.visit_reports()._headers()

        self.assertEqual(headers[5:], [
            'Teaching: Lesson pacing', 'Teaching: Questioning', 'Internal notes'])
