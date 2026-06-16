# webapp/class_visit/class_visit/reports/unscheduled_classes.py
import io
import csv

from django import forms
from django.urls import reverse_lazy
from django.core.files.base import ContentFile

from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.models.term import Term
from cis.models.highschool import HighSchool


class unscheduled_classes(forms.Form):
    """
    Export ClassSection rows that have no visit scheduled and are not
    marked as not-needed, filtered by the configured section_status_filter.
    """

    term = forms.ModelMultipleChoiceField(
        queryset=None,
        label='Term(s)',
        required=False,
        help_text='Leave blank to export all terms.',
    )
    highschool = forms.ModelMultipleChoiceField(
        queryset=None,
        label='High School(s)',
        required=False,
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
        self.fields['highschool'].queryset = HighSchool.objects.all()
        if request:
            self.roles = request.user.get_roles()
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    HEADERS = [
        'CRN',
        'Course',
        'Term',
        'High School',
        'Status',
        'Instructor',
    ]

    def _row(self, section):
        try:
            teacher_name = section.teacher.user.get_full_name()
        except Exception:
            teacher_name = ''
        return [
            section.class_number,
            section.course.name,
            section.term.label,
            section.highschool.name,
            section.status,
            teacher_name,
        ]

    def _get_queryset(self, data):
        from class_visit.class_visit.models import VisitSchedule, NotNeededVisit
        from class_visit.class_visit.settings.class_visit import class_visit as cv_settings
        from cis.models.section import ClassSection

        config = cv_settings.from_db()
        status_filter = config.get('section_status_filter') or 'all'

        # Map settings value ('active'/'inactive'/'all') to DB codes ('A'/'C').
        _STATUS_MAP = {
            'active': ['A'],
            'inactive': ['C'],
            'all': ['A', 'C'],
        }
        allowed_status_codes = _STATUS_MAP.get(
            status_filter if isinstance(status_filter, str) else 'all',
            ['A', 'C'],
        )

        # IDs already scheduled
        scheduled_ids = VisitSchedule.objects.values_list(
            'class_sections__id', flat=True
        )
        # IDs explicitly marked not-needed
        not_needed_ids = NotNeededVisit.objects.values_list(
            'class_section_id', flat=True
        )

        qs = ClassSection.objects.select_related(
            'course', 'term', 'highschool', 'teacher__user'
        ).exclude(
            id__in=scheduled_ids,
        ).exclude(
            id__in=not_needed_ids,
        )

        if status_filter != 'all':
            qs = qs.filter(status__in=allowed_status_codes)

        term_ids = data.get('term')
        if term_ids:
            qs = qs.filter(term__id__in=term_ids)

        hs_ids = data.get('highschool')
        if hs_ids:
            qs = qs.filter(highschool__id__in=hs_ids)

        return qs.order_by('term__label', 'highschool__name', 'class_number')

    def run(self, task, data):
        records = self._get_queryset(data)

        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(self.HEADERS)
        for section in records.iterator():
            writer.writerow(self._row(section))

        file_name = 'unscheduled-classes-export.csv'
        path = f'reports/{task.id}/{file_name}'
        storage = PrivateMediaStorage()
        path = storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        return storage.url(path)
