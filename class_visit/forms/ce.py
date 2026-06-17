"""CE Visit Schedule CRUD form."""
from django import forms
from django.core.exceptions import ValidationError
from django.utils.safestring import mark_safe

from cis.models.section import ClassSection
from cis.models.customuser import CustomUser
from cis.models.course import CourseAdministrator

from ..models import VisitSchedule
from ..settings.class_visit import class_visit as ClassVisitSettings


def _visit_type_choices(settings_dict):
    """Parse pipe-delimited visit_types from settings into form choices."""
    raw = settings_dict.get('visit_types', '')
    choices = [('', '--- Select ---')]
    for item in raw.split('|'):
        item = item.strip()
        if item:
            choices.append((item, item))
    return choices


class CEVisitScheduleForm(forms.Form):
    """Form for CE staff to add or edit a VisitSchedule.

    Args:
        section_id: UUID of a ClassSection — seeds visitor choices and
                    initial section choices from its course/teacher/term.
        visit_id:   UUID of an existing VisitSchedule to edit, or None/'-1' for create.
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
        widget=forms.DateInput(attrs={'class': 'col-4', 'type': 'date'}),
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

    notifications = forms.MultipleChoiceField(
        choices=[
            ('email_visitors', 'Email Visitor(s) with visit details'),
            ('email_instructor', 'Email Instructor with visit details'),
        ],
        required=False,
        label='Send Notifications (optional)',
        widget=forms.CheckboxSelectMultiple,
    )

    visit_id = forms.CharField(required=False, widget=forms.HiddenInput())

    def __init__(self, section_id=None, visit_id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        settings_dict = ClassVisitSettings.from_db()
        self.fields['type_of_visit'].choices = _visit_type_choices(settings_dict)

        if section_id:
            try:
                anchor = ClassSection.objects.get(pk=section_id)
            except ClassSection.DoesNotExist:
                anchor = None
        else:
            anchor = None

        if anchor:
            # Section choices: same teacher + term + course
            sections = ClassSection.objects.filter(
                teacher=anchor.teacher,
                term=anchor.term,
                course=anchor.course,
            )
            section_choices = [
                (
                    str(s.id),
                    mark_safe(
                        f'{s.course} / {s.term}'
                        f'<br><span class="text-muted">Period: {s.period_time}</span>'
                    ),
                )
                for s in sections
            ]
            self.fields['class_sections'].choices = section_choices
            self.fields['class_sections'].initial = [str(anchor.id)]

            # Visitor choices: active CourseAdministrators for the course
            admins_qs = CourseAdministrator.objects.filter(
                course=anchor.course,
                status__iexact='active',
            ).select_related('user')
            admins = list(admins_qs)
            self.fields['visitors'].choices = [
                (str(a.user.id), f"{a.user.last_name}, {a.user.first_name}")
                for a in admins
            ]
        else:
            self.fields['class_sections'].choices = []
            self.fields['visitors'].choices = []

        # Prepopulate for edit
        if visit_id and str(visit_id) != '-1':
            try:
                visit = VisitSchedule.objects.get(pk=visit_id)
                self.fields['visit_id'].initial = str(visit.id)
                if visit.visit_date:
                    self.fields['visit_date'].initial = (
                        visit.visit_date.strftime('%Y-%m-%d')
                    )
                self.fields['type_of_visit'].initial = visit.type_of_visit
                self.fields['pre_visit_note'].initial = (
                    visit.meta.get('pre_visit_note', '')
                )
                self.fields['notifications'].initial = (
                    visit.meta.get('visit_notifications', [])
                )
                self.fields['visitors'].initial = [
                    str(v.id) for v in visit.visitors.all()
                ]
                self.fields['class_sections'].initial = [
                    str(s.id) for s in visit.class_sections.all()
                ]
            except VisitSchedule.DoesNotExist:
                pass
        else:
            self.fields['visit_id'].initial = '-1'

    def clean_class_sections(self):
        """Validate all selected sections share one teacher."""
        ids = self.cleaned_data.get('class_sections', [])
        sections = list(ClassSection.objects.filter(id__in=ids))
        if len(sections) < 1:
            raise ValidationError('Select at least one class section.')
        if not VisitSchedule.sections_share_teacher(sections):
            raise ValidationError(
                'All selected class sections must be taught by the same instructor.'
            )
        return ids

    def save(self, request=None, commit=True):
        from ..services import emails as email_service

        data = self.cleaned_data
        visit_id = data.get('visit_id') or '-1'

        is_new = visit_id == '-1'

        if is_new:
            visit = VisitSchedule()
            visit.meta = {}
            visit.save()
        else:
            visit = VisitSchedule.objects.get(pk=visit_id)
            visit.class_sections.clear()
            visit.visitors.clear()

        visit.type_of_visit = data.get('type_of_visit', '')
        visit.visit_date = data.get('visit_date')
        visit.meta['pre_visit_note'] = data.get('pre_visit_note', '')
        visit.meta['visit_notifications'] = data.get('notifications', [])

        visit.save()

        sections = ClassSection.objects.filter(id__in=data.get('class_sections', []))
        for s in sections:
            visit.class_sections.add(s)

        visitors = CustomUser.objects.filter(id__in=data.get('visitors', []))
        for v in visitors:
            visit.visitors.add(v)

        if is_new:
            settings_dict = ClassVisitSettings.from_db()
            if settings_dict.get('notify_teacher_on_schedule') == 'Yes':
                email_service.notify_teacher_visit_scheduled(visit)

        return visit
