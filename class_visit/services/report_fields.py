"""
Service functions for dynamic report field definitions stored in class_visit settings.

Field def shape:
    {
      "name": str,           # snake_case field name (used as meta key)
      "label": str,          # human-readable label
      "type": str,           # one of: text, textarea, select, checkbox, date
      "public": bool,        # whether this field appears in the public report PDF
      "required": bool,
      "options": list[str],  # only used for type=select
    }
"""
import json

from django import forms


def _get_settings() -> dict:
    """Thin wrapper so tests can patch it without importing the settings class."""
    from ..settings.class_visit import class_visit as CVSettings
    return CVSettings.from_db()


def get_report_field_defs() -> list:
    """
    Return the list of report field definition dicts from settings.
    Returns [] on missing or invalid JSON.
    """
    cfg = _get_settings()
    raw = cfg.get('report_fields_json', '[]')
    try:
        defs = json.loads(raw)
        if not isinstance(defs, list):
            return []
        return defs
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


def public_field_names() -> set:
    """Return the set of field names that are marked public=True."""
    return {d['name'] for d in get_report_field_defs() if d.get('public')}


def build_report_form_fields(initial: dict = None) -> dict:
    """
    Build a dict of Django form field instances from the stored field definitions.

    Args:
        initial: optional dict of initial values keyed by field name.

    Returns:
        dict mapping field_name -> Django form field instance.
    """
    initial = initial or {}
    field_map = {}

    for defn in get_report_field_defs():
        name = defn.get('name', '')
        label = defn.get('label', name)
        required = bool(defn.get('required', False))
        field_type = defn.get('type', 'text')
        options = defn.get('options', [])
        initial_value = initial.get(name)

        if field_type == 'text':
            field = forms.CharField(
                label=label,
                required=required,
                initial=initial_value,
            )
        elif field_type == 'textarea':
            field = forms.CharField(
                label=label,
                required=required,
                widget=forms.Textarea,
                initial=initial_value,
            )
        elif field_type == 'select':
            choices = [(o, o) for o in options]
            if not required:
                choices = [('', '---')] + choices
            field = forms.ChoiceField(
                label=label,
                required=required,
                choices=choices,
                initial=initial_value,
            )
        elif field_type == 'checkbox':
            field = forms.BooleanField(
                label=label,
                required=False,  # BooleanField required=True means must be True, avoid that
                initial=initial_value,
            )
        elif field_type == 'date':
            field = forms.DateField(
                label=label,
                required=required,
                initial=initial_value,
                widget=forms.DateInput(attrs={'type': 'date'}),
            )
        else:
            field = forms.CharField(
                label=label,
                required=required,
                initial=initial_value,
            )

        field_map[name] = field

    return field_map


def report_values_for_display(visit_report, public_only: bool = False) -> list:
    """
    Return a list of {'label': str, 'value': any} dicts for display purposes.

    Args:
        visit_report: VisitReport instance (meta dict accessed via .meta).
        public_only: if True, only include fields with public=True.

    Returns:
        list of dicts in definition order.
    """
    defs = get_report_field_defs()
    result = []
    for defn in defs:
        if public_only and not defn.get('public'):
            continue
        name = defn.get('name', '')
        label = defn.get('label', name)
        value = visit_report.meta.get(name, '')
        result.append({'label': label, 'value': value})
    return result
