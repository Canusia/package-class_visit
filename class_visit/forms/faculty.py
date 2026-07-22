"""Faculty-facing forms for class visit scheduling and report writing."""
from django import forms
from django.core.exceptions import ValidationError
from django.utils.safestring import mark_safe

from cis.models.section import ClassSection
from cis.models.course import CourseAdministrator
from cis.models.customuser import CustomUser

from ..models import VisitSchedule, VisitReport, NotNeededVisit
from ..settings.class_visit import class_visit as ClassVisitSettings
from ..services import report_fields


def _status_filter_to_db(section_status_filter: str):
    """Map settings value to list of ClassSection.status DB codes."""
    mapping = {
        'active': ['A'],
        'inactive': ['C'],
        'all': ['A', 'C'],
    }
    return mapping.get(section_status_filter, ['A'])


class VisitScheduleForm(forms.Form):
    """Create or edit a VisitSchedule.

    Cross-field validators:
    - All selected class_sections share the same teacher.
    - None of the selected class_sections has a NotNeededVisit entry.
    - Each class_section status matches the configured section_status_filter.
    """

    class_sections = forms.MultipleChoiceField(
        choices=[],
        required=True,
        label='Class Section(s) to Visit',
        widget=forms.CheckboxSelectMultiple,
    )
    visitors = forms.MultipleChoiceField(
        choices=[],
        required=True,
        label='Visitor(s)',
        widget=forms.CheckboxSelectMultiple,
    )
    visit_date = forms.DateField(
        required=True,
        label='Visit Date',
        input_formats=['%m/%d/%Y', '%Y-%m-%d'],
        widget=forms.DateInput(attrs={'class': 'col-4', 'placeholder': 'MM/DD/YYYY'}),
    )
    type_of_visit = forms.ChoiceField(
        choices=[],
        required=True,
        label='Type of Visit',
    )
    pre_visit_note = forms.CharField(
        required=False,
        label='Pre-Visit Note',
        help_text='Visible only to visitors',
        widget=forms.Textarea(attrs={'rows': 3}),
    )

    def __init__(self, faculty_user, visit_schedule=None, anchor_section=None,
                 *args, **kwargs):
        """
        Args:
            faculty_user: The logged-in CustomUser with the faculty role.
            visit_schedule: Existing VisitSchedule instance for edit, or None for create.
            anchor_section: The ClassSection the visit is being managed from. When
                given, the selectable sections are limited to the same course
                taught by the same instructor as this section.
        """
        super().__init__(*args, **kwargs)
        self._faculty_user = faculty_user
        self._visit_schedule = visit_schedule
        self._anchor_section = anchor_section
        self._settings = ClassVisitSettings.from_db()

        # Populate visit_types choices from settings
        visit_types_raw = self._settings.get('visit_types', 'Observation')
        visit_type_choices = [
            (vt.strip(), vt.strip())
            for vt in visit_types_raw.split('|')
            if vt.strip()
        ]
        self.fields['type_of_visit'].choices = [('', '--- Select ---')] + visit_type_choices

        # Populate class_sections: sections the faculty user oversees.
        allowed_status_codes = _status_filter_to_db(
            self._settings.get('section_status_filter', 'active')
        )
        # Build course_ids from active CourseAdministrators.
        active_cas = list(CourseAdministrator.objects.filter(
            user=faculty_user,
            status__iexact='active',
        ))
        course_ids = [ca.course_id for ca in active_cas if ca.course_id is not None]

        # Sections: use select_related for production efficiency.
        sections_qs = ClassSection.objects.filter(
            course__id__in=course_ids,
            status__in=allowed_status_codes,
        ).select_related('teacher__user', 'course', 'term', 'highschool')

        # Anchor: limit choices to the same course taught by the same instructor
        # at the same high school as the section the visit is being managed from
        # (a visit's sections must share one instructor and one high school).
        if anchor_section is not None:
            sections_qs = sections_qs.filter(
                course_id=anchor_section.course_id,
                teacher_id=anchor_section.teacher_id,
                highschool_id=anchor_section.highschool_id,
            )

        sections = list(sections_qs)

        not_needed_ids = set(
            NotNeededVisit.objects.filter(
                class_section__in=sections
            ).values_list('class_section__id', flat=True)
        )

        section_choices = []
        for s in sections:
            if s.id not in not_needed_ids:
                section_choices.append((
                    str(s.id),
                    mark_safe(
                        f'{s.course} / {s.term} — {s.highschool}'
                        f'<br><span class="text-muted">Period: {s.period_time}</span>'
                    ),
                ))
        self.fields['class_sections'].choices = section_choices

        # Populate visitors: active CourseAdministrators for those courses,
        # deduped by user (a user may administer multiple of these courses).
        visitors_qs = CourseAdministrator.objects.filter(
            course__id__in=course_ids,
            status__iexact='active',
        ).select_related('user').order_by('user__last_name', 'user__first_name')

        seen_user_ids = set()
        visitor_choices = []
        for ca in visitors_qs:
            if ca.user_id in seen_user_ids:
                continue
            seen_user_ids.add(ca.user_id)
            visitor_choices.append(
                (str(ca.user.id), f'{ca.user.last_name}, {ca.user.first_name}')
            )
        self.fields['visitors'].choices = visitor_choices

        # Pre-populate for edit
        if visit_schedule:
            self.fields['visit_date'].initial = (
                visit_schedule.visit_date.strftime('%m/%d/%Y')
                if visit_schedule.visit_date else ''
            )
            self.fields['type_of_visit'].initial = visit_schedule.type_of_visit
            self.fields['pre_visit_note'].initial = visit_schedule.meta.get('pre_visit_note', '')
            self.fields['class_sections'].initial = [
                str(s.id) for s in visit_schedule.class_sections.all()
            ]
            self.fields['visitors'].initial = [
                str(u.id) for u in visit_schedule.visitors.all()
            ]
        elif anchor_section is not None:
            # New visit: pre-select the section it was launched from.
            self.fields['class_sections'].initial = [str(anchor_section.id)]

    def clean_class_sections(self):
        """Validate teacher-match, not-needed, and status constraints."""
        raw_ids = self.cleaned_data.get('class_sections', [])
        if not raw_ids:
            raise ValidationError('Select at least one class section.')

        settings_obj = self._settings
        allowed_status_codes = _status_filter_to_db(
            settings_obj.get('section_status_filter', 'active')
        )

        sections_qs = ClassSection.objects.filter(id__in=raw_ids).select_related('teacher__user')
        sections = list(sections_qs)

        # Status filter check
        bad_status = [s for s in sections if s.status not in allowed_status_codes]
        if bad_status:
            raise ValidationError(
                f'One or more sections have an ineligible status '
                f'(expected: {allowed_status_codes}).'
            )

        # Not-needed check
        not_needed_ids = set(
            NotNeededVisit.objects.filter(
                class_section__in=sections
            ).values_list('class_section__id', flat=True)
        )
        if not_needed_ids:
            raise ValidationError(
                'One or more selected sections are marked as not needing a visit.'
            )

        # Same-teacher check
        if not VisitSchedule.sections_share_teacher(sections):
            raise ValidationError(
                'All selected sections must have the same instructor.'
            )

        return raw_ids

    def save(self, commit=True):
        """Create or update a VisitSchedule from cleaned form data.

        On create: calls ensure_confirmation_token() and conditionally
        triggers notify_teacher_visit_scheduled() per settings.

        Returns:
            The saved VisitSchedule instance.
        """
        from ..services import emails as email_service

        data = self.cleaned_data

        if self._visit_schedule:
            visit = self._visit_schedule
            visit.class_sections.clear()
            visit.visitors.clear()
        else:
            visit = VisitSchedule()
            visit.meta = {}

        visit.visit_date = data['visit_date']
        visit.type_of_visit = data['type_of_visit']

        if data.get('pre_visit_note'):
            visit.meta['pre_visit_note'] = data['pre_visit_note']

        is_new = visit.pk is None

        if commit:
            visit.save()
            visit.class_sections.set(
                ClassSection.objects.filter(id__in=data['class_sections'])
            )
            visit.visitors.set(
                CustomUser.objects.filter(id__in=data['visitors'])
            )

            if is_new:
                visit.ensure_confirmation_token()
                if self._settings.get('notify_teacher_on_schedule') == 'Yes':
                    email_service.notify_teacher_visit_scheduled(visit)

        return visit


class VisitReportDynamicForm(forms.Form):
    """Dynamic form for writing/editing a visit report.

    Fields are generated at runtime by report_fields.build_report_form_fields().
    A hidden 'submit_action' field tracks Draft vs Submitted save intent.
    """

    submit_action = forms.CharField(
        widget=forms.HiddenInput(),
        initial='draft',
        required=False,
    )

    def __init__(self, visit, initial_meta=None, *args, **kwargs):
        """
        Args:
            visit: VisitSchedule instance this report belongs to.
            initial_meta: dict of existing report.meta values (or None for new report).
        """
        super().__init__(*args, **kwargs)
        self._visit = visit

        # Inject dynamic fields from the report_fields service
        dynamic_fields = report_fields.build_report_form_fields(
            initial=initial_meta,
            type_of_visit=getattr(visit, 'type_of_visit', None),
        )
        for field_name, field_obj in dynamic_fields.items():
            self.fields[field_name] = field_obj

    def save(self, created_by_user, commit=True):
        """Upsert VisitReport; flips status based on submit_action.

        When status transitions to 'Submitted':
        - Fires notify_teacher_report_submitted() if settings say Yes.
        - Always fires notify_notification_target().

        Returns:
            VisitReport instance.
        """
        from ..services import emails as email_service
        from ..settings.class_visit import class_visit as CVSettings

        settings_obj = CVSettings.from_db()
        data = self.cleaned_data

        submit_action = data.get('submit_action', 'draft').lower()
        new_status = 'Submitted' if submit_action == 'submit' else 'Draft'

        report, _created = VisitReport.objects.get_or_create(
            visit_schedule=self._visit,
            defaults={'meta': {}, 'status': 'Draft'},
        )

        # Write dynamic field values into meta
        for field_defn in report_fields.get_report_field_defs():
            name = field_defn.get('name', '') if isinstance(field_defn, dict) else field_defn
            if name in data:
                report.meta[name] = data[name]

        report.meta['created_by'] = str(created_by_user.id)
        was_draft = report.status != 'Submitted'
        report.status = new_status

        if commit:
            report.save()
            if new_status == 'Submitted' and was_draft:
                if settings_obj.get('notify_teacher_on_submit') == 'Yes':
                    email_service.notify_teacher_report_submitted(report)
                email_service.notify_notification_target(report)

        return report
