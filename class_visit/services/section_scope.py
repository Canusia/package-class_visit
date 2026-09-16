"""Section-selection rules shared by the CE and faculty scheduling forms.

Both forms must answer the same two questions — which section statuses a tenant
allows, and which sections are exempted via NotNeededVisit. They answered them
differently until #12: the CE form honoured neither. Keep the rules here rather
than copying them; two copies of a settings-to-DB-code mapping is how they drift.
"""
from ..models import NotNeededVisit

#: settings value -> ClassSection.status DB codes
_STATUS_MAP = {
    'active': ['A'],
    'inactive': ['C'],
    'all': ['A', 'C'],
}


def status_filter_to_db(section_status_filter: str):
    """Map the `section_status_filter` setting to ClassSection.status codes."""
    return _STATUS_MAP.get(section_status_filter, ['A'])


def not_needed_section_ids(sections):
    """Ids among `sections` that CE has flagged as not needing a visit."""
    return set(
        NotNeededVisit.objects.filter(class_section__in=sections)
        .values_list('class_section__id', flat=True)
    )
