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


# -- Secondary teachers on a class section (cis#154) ------------------------
#
# A secondary teacher sees and gets the emails for a section's class visits
# only when the Secondary Teacher Access setting allows CLASS_VISITS. On a cis
# without cis.secondary_access only the primary teacher counts, as before.

def _secondary_access():
    return (has_module('cis.secondary_access')
            and has_module('cis.models.section_secondary'))


def teacher_visits_q(teacher, prefix='class_sections__'):
    """Q for visits (or rows reaching sections through `prefix`) on sections
    where `teacher` may do class visits: primary sections, plus secondary ones
    when the setting allows. On the M2M this can repeat a visit: distinct()."""
    from django.db.models import Q
    if not _secondary_access():
        return Q(**{f'{prefix}teacher': teacher})
    from cis.models.section_secondary import teacher_q
    from cis.secondary_access import CLASS_VISITS, secondary_allowed
    return teacher_q(teacher=teacher, prefix=prefix,
                     include_secondary=secondary_allowed(CLASS_VISITS))


def teacher_filter_q(teacher_id, prefix='class_sections__'):
    """CE filter: sections taught by `teacher_id` as primary or secondary
    (not limited by the setting)."""
    from django.db.models import Q
    if not has_module('cis.models.section_secondary'):
        return Q(**{f'{prefix}teacher__id': teacher_id})
    from cis.models.section_secondary import teacher_q
    return teacher_q(teacher=teacher_id, prefix=prefix)


def notified_teachers(section):
    """Teachers emailed about `section`'s class visits: the primary, plus
    secondaries when the setting allows CLASS_VISITS."""
    if not _secondary_access():
        teacher = getattr(section, 'teacher', None)
        return [teacher] if teacher is not None else []
    from cis.secondary_access import CLASS_VISITS
    from cis.secondary_access import notified_teachers as notified
    return notified(section, CLASS_VISITS)
