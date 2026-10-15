"""Term pickers and filters that follow the parent/sub-term hierarchy.

Thin wrappers over cis.services.term_hierarchy (package-cis v0.1.19a). A parent
term in a filter means "this term and its sub-terms" -- a tenant whose active term
is a parent keeps every section on a sub-term, so an exact match found nothing.
On an older cis they fall back to a flat list and an exact-term filter.
"""


def term_choices(terms):
    """[(id, label)]: sub-terms indented under their parent."""
    terms = list(terms)
    try:
        from cis.services.term_hierarchy import term_tree_choices
    except ImportError:  # cis without the term hierarchy
        return [(str(term.pk), str(term)) for term in terms]
    return term_tree_choices(terms)


def filter_by_term(queryset, term_id, field='term'):
    """`term_id` and its sub-terms (exact term only on an older cis)."""
    try:
        from cis.services.term_hierarchy import filter_by_term as _filter
    except ImportError:  # cis without the term hierarchy
        return queryset.filter(**{f'{field}__id': term_id})
    return _filter(queryset, term_id, field=field)
