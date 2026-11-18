"""Plain-text form errors for the iframe modals, which show only ``message``
(a swal or alert). Without this, a validation error such as a closed
class-visit window (#24) or a teacherless mix (#26) reached the user as a
bare "Please fix the errors below." with nothing below."""


def error_message(form, lead='Please fix the following and try again:'):
    parts = []
    for name, errors in form.errors.items():
        field = form.fields.get(name)
        label = str(field.label) if field is not None and field.label else ''
        for error in errors:
            parts.append(f'{label}: {error}' if label else str(error))
    return ' '.join([lead] + parts) if parts else lead
