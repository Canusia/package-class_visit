# webapp/class_visit/class_visit/reports/visit_reports.py
import io
import csv

from django import forms
from django.urls import reverse_lazy
from django.core.files.base import ContentFile

from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.models.term import Term
from ..services.report_fields import get_report_field_defs


class visit_reports(forms.Form):
    """Export submitted visit reports, one row per report, with configured field columns."""

    term = forms.ModelMultipleChoiceField(
        queryset=None,
        label='Term(s)',
        required=False,
        help_text='Leave blank to export all terms.',
    )

    roles = []
    request = None

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.helper = FormHelper()
        self.helper.attrs = {'target': '_blank'}
        self.helper.form_method = 'POST'
        self.helper.add_input(Submit('submit', 'Generate Export'))
        self.fields['term'].queryset = Term.objects.all()
        if request:
            self.roles = request.user.get_roles()
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _field_defs(self):
        return get_report_field_defs()

    def _headers(self):
        static = ['Visit Date', 'Type of Visit', 'Sections (CRN)', 'Teacher', 'Report Status']
        # Support both 'name' (real service) and 'key' (legacy/test mocks) as the field key
        dynamic = [fd['label'] for fd in self._field_defs()]
        return static + dynamic

    def _row(self, report):
        visit = report.visit_schedule
        visit_date_str = visit.visit_date.strftime('%m/%d/%Y') if visit.visit_date else ''
        crns = ', '.join(s.class_number for s in visit.class_sections.all())
        teacher_name = visit.teacher.get_full_name() if visit.teacher else ''
        static = [visit_date_str, visit.type_of_visit, crns, teacher_name, report.status]
        meta = report.meta or {}
        # Use 'name' field as the meta key (matches real get_report_field_defs shape)
        dynamic = [str(meta.get(fd.get('name', fd.get('key', '')), '')) for fd in self._field_defs()]
        return static + dynamic

    def _get_queryset(self, data):
        from ..models import VisitReport

        qs = VisitReport.objects.filter(
            status='Submitted',
        ).select_related(
            'visit_schedule',
        ).prefetch_related(
            'visit_schedule__class_sections',
            'visit_schedule__class_sections__term',
            'visit_schedule__visitors',
        )

        term_ids = data.get('term')
        if term_ids:
            qs = qs.filter(
                visit_schedule__class_sections__term__id__in=term_ids
            ).distinct()

        return qs.order_by('visit_schedule__visit_date')

    def run(self, task, data):
        records = self._get_queryset(data)

        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(self._headers())
        for report in records.iterator():
            writer.writerow(self._row(report))

        file_name = 'visit-reports-export.csv'
        path = f'reports/{task.id}/{file_name}'
        storage = PrivateMediaStorage()
        path = storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        return storage.url(path)
