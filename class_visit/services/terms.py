"""Term pickers and filters that follow the parent/sub-term hierarchy.

Thin wrappers over cis.services.term_hierarchy (package-cis v0.1.19a). A parent
term in a filter means "this term and its sub-terms" -- a tenant whose active term
is a parent keeps every section on a sub-term, so an exact match found nothing.
On an older cis they fall back to a flat list and an exact-term filter.
"""
from .. import compat

_HIERARCHY = 'cis.services.term_hierarchy'


def term_choices(terms):
    """[(id, label)]: sub-terms indented under their parent."""
    terms = list(terms)
    if not compat.has_module(_HIERARCHY):  # cis without the term hierarchy
        return [(str(term.pk), str(term)) for term in terms]
    from cis.services.term_hierarchy import term_tree_choices
    return term_tree_choices(terms)


def filter_by_term(queryset, term_id, field='term'):
    """`term_id` and its sub-terms (exact term only on an older cis)."""
    if not compat.has_module(_HIERARCHY):  # cis without the term hierarchy
        return queryset.filter(**{f'{field}__id': term_id})
    from cis.services.term_hierarchy import filter_by_term as _filter
    return _filter(queryset, term_id, field=field)


# -- Class-visit window (#24) -------------------------------------------------
#
# cis v0.2.12a adds Term.visit_window_opens_on / visit_window_closes_on, which a
# sub-term inherits from its parent. Faculty may schedule visits only on terms
# whose window is open today. Until any term has a window, every term is open
# (today's behaviour), and on an older cis without the fields nothing changes.

WINDOW_FIELDS = ('visit_window_opens_on', 'visit_window_closes_on')
_MAX_DEPTH = 10


def has_visit_window_fields():
    from cis.models.term import Term
    names = {f.name for f in Term._meta.get_fields()}
    return all(name in names for name in WINDOW_FIELDS)


def open_visit_term_ids(today=None):
    """Ids of the terms whose class-visit window is open on ``today``, or None
    when no window applies (no fields, or no term has a window set).

    A window is open from its opening day through its closing day, either end
    may be blank (no limit on that side), and a term with neither date set,
    on itself or a parent, is closed once windows are in use."""
    if not has_visit_window_fields():
        return None
    from django.utils import timezone
    from cis.models.term import Term
    rows = {r['id']: r for r in Term.objects.values('id', 'parent_id', *WINDOW_FIELDS)}
    if not any(r[f] for r in rows.values() for f in WINDOW_FIELDS):
        return None
    today = today or timezone.localdate()

    def effective(row, field):
        for _ in range(_MAX_DEPTH):
            if row is None:
                return None
            if row[field] is not None:
                return row[field]
            row = rows.get(row['parent_id'])
        return None

    ids = set()
    for term_id, row in rows.items():
        opens, closes = (effective(row, f) for f in WINDOW_FIELDS)
        if opens is None and closes is None:
            continue
        if (opens is None or opens <= today) and (closes is None or today <= closes):
            ids.add(term_id)
    return ids


def closed_visit_terms(sections, today=None):
    """The distinct terms of ``sections`` whose class-visit window is closed
    (empty when no window applies)."""
    ids = open_visit_term_ids(today)
    if ids is None:
        return []
    seen, closed = set(), []
    for section in sections:
        term = section.term
        if term is not None and term.pk not in ids and term.pk not in seen:
            seen.add(term.pk)
            closed.append(term)
    return closed
