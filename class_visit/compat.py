"""Optional cis modules, with fallbacks for tenants that keep an older cis in
their own repo (nnu and others; issue #20).

Availability is checked with ``find_spec`` rather than ``try/except
ImportError``, so a real import error inside a present module still raises
instead of silently turning into the fallback.
"""
import importlib.util


def has_module(name):
    """True when the dotted module ``name`` is importable."""
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:  # a parent package is missing
        return False


def scope_highschools(queryset, user=None):
    """``cis.highschool_scope.scope_highschools``, or ``queryset`` unchanged
    on a cis without campus-scoped schools (the pre-v0.0.18 behaviour)."""
    if not has_module('cis.highschool_scope'):
        return queryset
    from cis.highschool_scope import scope_highschools as scoped
    return scoped(queryset, user=user)
