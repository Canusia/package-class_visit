# webapp/class_visit/class_visit/reports/pending_visit_reports.py
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


class pending_visit_reports(forms.Form):
    """
    Export VisitSchedule rows whose visit_date has passed and whose
    report is missing or not yet Submitted.
    """

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

    HEADERS = [
        'Visit Date',
        'Type of Visit',
        'Days Past Visit',
        'Sections (CRN)',
        'Teacher',
        'Visitors',
        'Report Status',
    ]

    def _row(self, visit, today=None):
        today = today or datetime.date.today()
        visit_date_str = visit.visit_date.strftime('%m/%d/%Y') if visit.visit_date else ''
        days_past = (today - visit.visit_date).days if visit.visit_date else ''
        crns = ', '.join(s.class_number for s in visit.class_sections.all())
        teacher_name = visit.teacher.get_full_name() if visit.teacher else ''
        visitors = ', '.join(v.get_full_name() for v in visit.visitors.all())

        try:
            status = visit.report.status
        except Exception:
            status = 'Missing'

        return [visit_date_str, visit.type_of_visit, days_past, crns, teacher_name, visitors, status]

    def _get_queryset(self, data):
        from class_visit.class_visit.models import VisitSchedule

        today = datetime.date.today()

        # Past visits where report is missing OR not Submitted
        qs = VisitSchedule.objects.filter(
            visit_date__lt=today,
        ).exclude(
            report__status='Submitted',
        ).prefetch_related(
            'class_sections',
            'class_sections__term',
            'visitors',
        ).select_related('report')

        term_ids = data.get('term')
        if term_ids:
            qs = qs.filter(class_sections__term__id__in=term_ids).distinct()

        return qs.order_by('visit_date')

    def run(self, task, data):
        today = datetime.date.today()
        records = self._get_queryset(data)

        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(self.HEADERS)
        for visit in records.iterator():
            writer.writerow(self._row(visit, today))

        file_name = 'pending-visit-reports-export.csv'
        path = f'reports/{task.id}/{file_name}'
        storage = PrivateMediaStorage()
        path = storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        return storage.url(path)
