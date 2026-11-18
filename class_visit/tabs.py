"""Tabs on the faculty class-visits page, ``/faculty/class_visits/`` (#25).

An index page with no record: the view calls
``faculty_visit_tabs.for_record(request, None, url_for)`` and the template
renders the nav from the result and each pane only when its tab is present.
Handlers return nothing because the panes are server-rendered DataTables.

Tenants change the tabs in their own ``myce/component_registry/*.py``::

    from class_visit.tabs import faculty_visit_tabs   # or class_visit.class_visit.tabs
    faculty_visit_tabs.disable('schedule_visit')
    faculty_visit_tabs.set_active('all')

On a cis without ``cis.tabs.registry`` (or a tenant without
``myce.component_registry``) a small local registry with the same API is
used, so the page renders the same.
"""
from collections import OrderedDict

from . import compat


class _LocalTabRegistry:
    """The subset of cis's IndexTabRegistry this page needs."""

    def __init__(self):
        self._tabs = OrderedDict()

    def tab(self, slug, title, order, active=False, permission=None, icon=None, **_):
        def decorator(fn):
            self._tabs[slug] = {'handler': fn, 'title': title, 'order': order,
                                'active': active, 'permission': permission,
                                'icon': icon}
            return fn
        return decorator

    def disable(self, *slugs):
        for slug in slugs:
            if slug not in self._tabs:
                raise KeyError(f'Cannot disable unknown tab {slug!r}. '
                               f'Registered: {sorted(self._tabs)}')
            del self._tabs[slug]

    def set_active(self, slug):
        if slug not in self._tabs:
            raise KeyError(f'Cannot activate unknown tab {slug!r}. '
                           f'Registered: {sorted(self._tabs)}')
        for s, t in self._tabs.items():
            t['active'] = (s == slug)

    def for_record(self, request, record, url_for):
        rows = []
        for slug, t in self._tabs.items():
            if t['permission'] and not t['permission'](request.user, record):
                continue
            rows.append((slug, {'slug': slug, 'title': t['title'], 'icon': t['icon'],
                                'order': t['order'], 'active': t['active'],
                                'hidden': False, 'url': url_for(slug)}))
        rows.sort(key=lambda kv: kv[1]['order'])
        tabs = OrderedDict(rows)
        visible = list(tabs.values())
        if visible and not any(t['active'] for t in visible):
            visible[0]['active'] = True
        return tabs


def _registry_class():
    if compat.has_module('cis.tabs.registry'):
        try:
            from cis.tabs.registry import IndexTabRegistry
            return IndexTabRegistry
        except ImportError:  # e.g. the tenant ships no myce.component_registry
            pass
    return _LocalTabRegistry


def _pane(request, record):
    return {}


def _may_view_others(user, record):
    from .services.scope import faculty_can_view_others_visits
    return faculty_can_view_others_visits()


def build_faculty_visit_tabs():
    """A fresh registry with the default tabs (tests build their own)."""
    registry = _registry_class()()
    registry.tab(slug='schedule_visit', title='Add Observation Date(s)', order=10,
                 icon='fas fa-plus', active=True)(_pane)
    registry.tab(slug='all', title='My Observations', order=20)(_pane)
    registry.tab(slug='others', title="Other Faculty's Observations", order=30,
                 permission=_may_view_others)(_pane)
    return registry


faculty_visit_tabs = build_faculty_visit_tabs()
