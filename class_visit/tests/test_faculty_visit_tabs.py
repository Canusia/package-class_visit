"""#25: the faculty class-visits tabs come from a tab registry, so a tenant can
disable, reorder or retitle them or pick the default without overriding the
template. Other Faculty's Observations keeps its setting gate."""
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase
from django.urls import reverse

from cis.models.settings import Setting

from . import PKG
from .test_views_faculty import User, _disconnect_login_signal, _reconnect_login_signal, _sfx
from .. import tabs as tabs_module
from ..tabs import build_faculty_visit_tabs

NAV = 'data-toggle="tab" href="#{}"'
PANE = 'id="{}"'


def _set_others(value):
    Setting.objects.update_or_create(
        key='class_visit', defaults={'value': {'faculty_view_others_visits': value}})


class RegistryTest(TestCase):

    def _tabs(self, registry=None):
        request = RequestFactory().get('/')
        request.user = User(username='x')
        registry = registry or build_faculty_visit_tabs()
        return registry.for_record(request, None, lambda slug: '')

    def test_default_tabs_in_order(self):
        _set_others('No')
        tabs = self._tabs()
        self.assertEqual(list(tabs), ['schedule_visit', 'all'])
        self.assertTrue(tabs['schedule_visit']['active'])
        self.assertEqual(tabs['all']['title'], 'My Observations')

    def test_others_tab_follows_the_setting(self):
        _set_others('Yes')
        self.assertEqual(list(self._tabs()), ['schedule_visit', 'all', 'others'])

    def test_disabling_the_default_activates_the_first_visible(self):
        registry = build_faculty_visit_tabs()
        registry.disable('schedule_visit')
        tabs = self._tabs(registry)
        self.assertEqual(list(tabs), ['all'])
        self.assertTrue(tabs['all']['active'])

    def test_set_active(self):
        registry = build_faculty_visit_tabs()
        registry.set_active('all')
        tabs = self._tabs(registry)
        self.assertTrue(tabs['all']['active'])
        self.assertFalse(tabs['schedule_visit']['active'])

    def test_unknown_slug_raises(self):
        with self.assertRaises(KeyError):
            build_faculty_visit_tabs().disable('nope')

    def test_works_without_the_cis_tab_registry(self):
        with patch(f'{PKG}.tabs.compat.has_module', return_value=False):
            registry = build_faculty_visit_tabs()
        self.assertNotIn('IndexTabRegistry', [c.__name__ for c in type(registry).__mro__])
        registry.disable('schedule_visit')
        _set_others('Yes')
        tabs = self._tabs(registry)
        self.assertEqual(list(tabs), ['all', 'others'])
        self.assertTrue(tabs['all']['active'])


class PageTest(TestCase):

    def setUp(self):
        self._receivers = _disconnect_login_signal()
        self.user = User.objects.create(
            username=f'fvt_{_sfx()}@x.com', email=f'fvt_{_sfx()}@x.com', is_active=True)
        self.user.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.client.force_login(self.user)

    def tearDown(self):
        _reconnect_login_signal(self._receivers)

    def _html(self, registry=None):
        registry = registry or build_faculty_visit_tabs()
        with patch(f'{PKG}.views.faculty.faculty_visit_tabs', registry):
            resp = self.client.get(reverse('faculty_class_visit:visits'))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_default_page_unchanged(self):
        _set_others('No')
        html = self._html()
        for slug in ('schedule_visit', 'all'):
            self.assertIn(NAV.format(slug), html)
            self.assertIn(PANE.format(slug), html)
        self.assertNotIn(NAV.format('others'), html)
        self.assertNotIn(PANE.format('others'), html)
        self.assertIn('Add Observation Date(s)', html)
        self.assertIn('<div class="tab-pane active" id="schedule_visit">', html)

    def test_others_tab_shown_when_enabled(self):
        _set_others('Yes')
        html = self._html()
        self.assertIn(NAV.format('others'), html)
        self.assertIn(PANE.format('others'), html)

    def test_disabled_tab_leaves_nav_and_pane(self):
        registry = build_faculty_visit_tabs()
        registry.disable('schedule_visit')
        html = self._html(registry)
        self.assertNotIn(NAV.format('schedule_visit'), html)
        self.assertNotIn(PANE.format('schedule_visit'), html)
        self.assertIn('<div class="tab-pane active" id="all">', html)

    def test_retitled_tab(self):
        registry = build_faculty_visit_tabs()
        registry._tabs['all']['title'] = 'Visits I Made'
        self.assertIn('Visits I Made', self._html(registry))

    def test_module_level_registry_exists(self):
        self.assertTrue(hasattr(tabs_module, 'faculty_visit_tabs'))
