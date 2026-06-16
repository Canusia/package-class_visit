# webapp/class_visit/class_visit/reports/scheduled_visits.py
import io
import csv
import datetime

from django import forms
from django.urls import reverse_lazy
from django.core.files.base import ContentFile

from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.models.term import Term


class scheduled_visits(forms.Form):
    """Export all scheduled visits with section, visitor, and report-status columns."""

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
    # Public helpers
    # ------------------------------------------------------------------

    HEADERS = [
        'Visit Date',
        'Type of Visit',
        'Sections (CRN)',
        'Teacher',
        'Visitors',
        'Report Status',
    ]

    def _row(self, visit):
        """Build a single CSV row from a VisitSchedule instance."""
        crns = ', '.join(s.class_number for s in visit.class_sections.all())
        visitors = ', '.join(v.get_full_name() for v in visit.visitors.all())
        teacher_name = visit.teacher.get_full_name() if visit.teacher else ''
        visit_date_str = visit.visit_date.strftime('%m/%d/%Y') if visit.visit_date else ''

        try:
            status = visit.report.status
        except Exception:
            status = 'No Report'

        return [visit_date_str, visit.type_of_visit, crns, teacher_name, visitors, status]

    def _get_queryset(self, data):
        from class_visit.class_visit.models import VisitSchedule

        qs = VisitSchedule.objects.prefetch_related(
            'class_sections',
            'visitors',
            'class_sections__term',
        ).select_related('report')

        term_ids = data.get('term')
        if term_ids:
            qs = qs.filter(class_sections__term__id__in=term_ids).distinct()

        return qs.order_by('visit_date')

    def run(self, task, data):
        records = self._get_queryset(data)

        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(self.HEADERS)
        for visit in records.iterator():
            writer.writerow(self._row(visit))

        file_name = 'scheduled-visits-export.csv'
        path = f'reports/{task.id}/{file_name}'
        storage = PrivateMediaStorage()
        path = storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        return storage.url(path)
