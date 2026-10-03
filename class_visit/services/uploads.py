"""Visit report attachments: visitor uploads, limits, listings and downloads.

Files are `VisitReportFile` rows. `kind` records who attached them:
`faculty_attachment` (a visitor, on the report form) or `instructor_response`
(the instructor, on the sign-off panel, #14). The storage is private, so every
download goes through a scoped view that calls `file_response()`. Never use a raw
storage URL.
"""
import os

from django import forms
from django.core.exceptions import ValidationError
from django.http import FileResponse
from django.urls import reverse

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = (
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'csv',
    'jpg', 'jpeg', 'png', 'gif', 'heic',
)
# Report-form field name; prefixed so a configured report field can't shadow it.
FIELD_NAME = 'cv_visitor_files'


def _settings():
    from ..settings.class_visit import class_visit as ClassVisitSettings
    return ClassVisitSettings.from_db()


def uploads_enabled():
    """Visitors may attach files to the report (`visitor_file_upload`)."""
    return _settings().get('visitor_file_upload', 'No') == 'Yes'


def instructor_sees_visitor_files():
    """The instructor may see/download visitor files (`instructor_view_visitor_files`)."""
    return _settings().get('instructor_view_visitor_files', 'No') == 'Yes'


def visitor_file_required():
    """Submit needs a visitor file (`visitor_file_required`, only with uploads on)."""
    s = _settings()
    return (s.get('visitor_file_upload', 'No') == 'Yes'
            and s.get('visitor_file_required', 'No') == 'Yes')


def instructor_file_required():
    """Sign-off needs an instructor file (`instructor_file_required`, only with sign-off on)."""
    s = _settings()
    return (s.get('instructor_signature', 'No') == 'Yes'
            and s.get('instructor_file_required', 'No') == 'Yes')


def has_files(visit, kind):
    from ..models import VisitReportFile
    return VisitReportFile.objects.filter(
        visit_report__visit_schedule=visit, kind=kind).exists()


VISITOR_FILE_REQUIRED_MSG = 'Attach at least one file before submitting the report.'


def validate_upload(f):
    ext = os.path.splitext(f.name)[1].lower().lstrip('.')
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f'"{f.name}": file type not allowed. Allowed: {", ".join(ALLOWED_EXTENSIONS)}.')
    if f.size > MAX_UPLOAD_BYTES:
        raise ValidationError(
            f'"{f.name}" is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.')


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """A FileField that accepts several files and validates each one."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('widget', MultipleFileInput())
        kwargs.setdefault('validators', [validate_upload])
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(d, initial) for d in data if d]
        return [single(data, initial)] if data else []


def build_upload_field(required_to_submit=False):
    return MultipleFileField(
        required=False,  # drafts never need one; Submit is checked in the form's clean()
        label='Attach files (required to submit)' if required_to_submit
        else 'Attach files (optional)',
        help_text=(
            f'Up to {MAX_UPLOAD_BYTES // (1024 * 1024)} MB each. '
            f'Allowed: {", ".join(ALLOWED_EXTENSIONS)}.'
        ),
    )


def save_visitor_files(report, files, user):
    from ..models import VisitReportFile
    return [
        VisitReportFile.objects.create(
            visit_report=report, file=f, uploaded_by=user,
            kind=VisitReportFile.FACULTY_ATTACHMENT)
        for f in files
    ]


def display_name(report_file):
    return os.path.basename(report_file.file.name)


def visible_files(report, portal):
    """The report's attachments a portal may list: 'ce', 'faculty' or 'instructor'."""
    from ..models import VisitReportFile
    if report is None:
        return []
    qs = report.files.select_related('uploaded_by').order_by('uploaded_at')
    if portal == 'instructor':
        if report.status != 'Submitted':
            return []
        if not instructor_sees_visitor_files():
            qs = qs.filter(kind=VisitReportFile.INSTRUCTOR_RESPONSE)
    return list(qs)


_DOWNLOAD_URL = {
    'ce': 'class_visit:ce_download_file',
    'faculty': 'faculty_class_visit:download_file',
    'instructor': 'instructor_class_visit:download_file',
}


def attachment_rows(report, portal, can_remove=False):
    """Display rows for `class_visit/_attachments.html`."""
    from ..models import VisitReportFile
    rows = []
    for f in visible_files(report, portal):
        kwargs = {'visit_id': report.visit_schedule_id, 'file_id': f.id}
        rows.append({
            'name': display_name(f),
            'kind': f.get_kind_display(),
            'uploaded_by': f.uploaded_by.get_full_name() if f.uploaded_by else '',
            'uploaded_at': f.uploaded_at,
            'url': reverse(_DOWNLOAD_URL[portal], kwargs=kwargs),
            'remove_url': (
                reverse('faculty_class_visit:remove_file', kwargs=kwargs)
                if can_remove and report.status != 'Submitted'
                and f.kind == VisitReportFile.FACULTY_ATTACHMENT else ''
            ),
        })
    return rows


def file_response(report_file):
    return FileResponse(
        report_file.file.open('rb'), as_attachment=True,
        filename=display_name(report_file))
