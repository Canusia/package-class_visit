"""Fallbacks for tenants whose cis predates the modules class_visit uses (#20).

Each test patches ``compat.has_module`` to report a module missing, which is
the only thing that differs on an in-repo-cis tenant (nnu, ...).
"""
import importlib
from unittest import mock

from django.template import Context, Template
from django.test import SimpleTestCase, TestCase

from cis.models.highschool import HighSchool

from .. import compat
from ..services import terms
from ..templatetags import class_visit_brand


def _missing(*names):
    real = compat.has_module
    return mock.patch.object(
        compat, 'has_module', side_effect=lambda name: name not in names and real(name))


class HasModuleTests(SimpleTestCase):
    def test_present_and_absent_modules(self):
        self.assertTrue(compat.has_module('cis.models'))
        self.assertFalse(compat.has_module('cis.no_such_module'))
        self.assertFalse(compat.has_module('no_such_pkg.child'))


class ScopeHighschoolsFallbackTests(TestCase):
    def test_without_highschool_scope_queryset_is_unchanged(self):
        qs = HighSchool.objects.all()
        with _missing('cis.highschool_scope'):
            self.assertIs(compat.scope_highschools(qs, user=None), qs)

    def test_report_form_lists_every_school_without_highschool_scope(self):
        from ..reports.unscheduled_classes import unscheduled_classes
        HighSchool.objects.create(name='Compat Any', code='cmpany')
        with _missing('cis.highschool_scope'):
            names = list(unscheduled_classes().fields['highschool']
                         .queryset.values_list('name', flat=True))
        self.assertIn('Compat Any', names)


class TermHierarchyFallbackTests(SimpleTestCase):
    def test_flat_choices_without_term_hierarchy(self):
        term = mock.Mock(pk='t1', __str__=lambda self: 'Fall 2026')
        with _missing('cis.services.term_hierarchy'):
            self.assertEqual(terms.term_choices([term]), [('t1', 'Fall 2026')])

    def test_exact_term_filter_without_term_hierarchy(self):
        queryset = mock.Mock()
        with _missing('cis.services.term_hierarchy'):
            terms.filter_by_term(queryset, 't1', field='class_section__term')
        queryset.filter.assert_called_once_with(class_section__term__id='t1')


class BrandTagFallbackTests(SimpleTestCase):
    def test_templates_load_the_package_library(self):
        """No class_visit template loads cis's `brand` library directly."""
        import pathlib
        root = pathlib.Path(compat.__file__).parent / 'templates'
        offenders = [str(p.relative_to(root)) for p in root.rglob('*.html')
                     if '{% load static brand %}' in p.read_text()
                     or '{% load brand %}' in p.read_text()]
        self.assertEqual(offenders, [])

    def test_no_op_tags_without_cis_brand(self):
        with _missing('cis.templatetags.brand'):
            module = importlib.reload(class_visit_brand)
        try:
            self.assertEqual(set(module.register.tags),
                             {'brand', 'brand_logo_url', 'brand_background_url', 'brand_css'})
            for name in module.register.tags:
                self.assertEqual(getattr(module, name)(), '')
        finally:
            importlib.reload(class_visit_brand)



class BrandTagPassThroughTests(TestCase):
    def test_passes_through_to_cis_brand_when_present(self):
        if not compat.has_module('cis.templatetags.brand'):
            self.skipTest('cis without brand tags')
        from cis.templatetags import brand
        self.assertIs(class_visit_brand.register, brand.register)
        html = Template('{% load class_visit_brand %}[{% brand_css %}]').render(Context({}))
        self.assertTrue(html.startswith('['))
