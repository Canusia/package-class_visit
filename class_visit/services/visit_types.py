"""Per-visit-type instructor options (#21).

Each configured Visit Type can turn off, for the observed instructor:

- ``notify_on_schedule``: the "visit scheduled" email,
- ``notify_on_submit``: the "report submitted" email,
- ``instructor_visible``: the visit in the instructor portal. A hidden type
  also gets neither instructor email, since both link into the portal.

Stored in the ``visit_type_options`` setting as a JSON object keyed by type
name. A type with no entry (or a key left out) counts as Yes, so tenants that
never set it keep today's behaviour. Read when an email is sent or a page is
loaded, so changing a type's options also applies to its existing visits.

The global Notify Teacher switches stay master switches: an instructor email
needs the global switch *and* the type's option.
"""
import json

from django.db.models import Q

OPTION_KEYS = ('notify_on_schedule', 'notify_on_submit', 'instructor_visible')


def _settings():
    from ..settings.class_visit import class_visit as CVSettings
    return CVSettings.from_db()


def parse_options(raw):
    """``visit_type_options`` as a dict (accepts the stored JSON string, a
    dict, or nothing); anything malformed counts as no options."""
    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except ValueError:
            return {}
    else:
        return {}
    return data if isinstance(data, dict) else {}


def type_options(cfg=None):
    cfg = _settings() if cfg is None else cfg
    return parse_options(cfg.get('visit_type_options'))


def _option(type_name, key, cfg=None):
    entry = type_options(cfg).get(type_name or '')
    if not isinstance(entry, dict):
        return True
    return entry.get(key, True) is not False


def instructor_visible(visit, cfg=None):
    return _option(visit.type_of_visit, 'instructor_visible', cfg)


def notify_on_schedule(visit, cfg=None):
    cfg = _settings() if cfg is None else cfg
    return (instructor_visible(visit, cfg)
            and _option(visit.type_of_visit, 'notify_on_schedule', cfg))


def notify_on_submit(visit, cfg=None):
    cfg = _settings() if cfg is None else cfg
    return (instructor_visible(visit, cfg)
            and _option(visit.type_of_visit, 'notify_on_submit', cfg))


def hidden_types(cfg=None):
    return sorted(
        name for name, entry in type_options(cfg).items()
        if isinstance(entry, dict) and entry.get('instructor_visible', True) is False)


def visible_q(prefix='', cfg=None):
    """Q excluding visits whose type is hidden from instructors; an empty Q
    (matches everything) when no type is hidden."""
    hidden = hidden_types(cfg)
    if not hidden:
        return Q()
    return ~Q(**{f'{prefix}type_of_visit__in': hidden})
