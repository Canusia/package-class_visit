import re

from django import forms
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils.safestring import mark_safe

from form_fields import fields as FFields

from cis.models.term import Term
from cis.models.customuser import CustomUser

from cis.models.section import ClassSection
from cis.models.course import CourseAdministrator
from uuid import UUID

from cis.utils import (
    YES_NO_OPTIONS, STUDENT_GRADE_OPTIONS, STUDENT_GPA_OPTIONS,
    registration_terms, user_has_cis_role, is_valid_address,
    active_term as get_active_term
)

from ..models import VisitSchedule, VisitReport, VisitReportFile

class VisitScheduleForm(forms.Form):

    class_sections = forms.MultipleChoiceField(
        choices=[],
        required=True,
        label='Class Section(s) Visiting',
        widget=forms.CheckboxSelectMultiple
    )
    
    visitors = forms.MultipleChoiceField(
        choices=[],
        required=True,
        label='Visitor(s)',
        widget=forms.CheckboxSelectMultiple
    )

    visit_date = forms.DateField(
        required=False,
        label='Visit Date',
        widget=forms.DateInput(attrs={'class':'col-4'})
    )
    
    visit_id = forms.CharField(
        required=True,
        widget=forms.HiddenInput()
    )

    checklink = forms.MultipleChoiceField(
        choices=[
            ('item1', 'Item 1'),
            ('item2', 'Item 2'),
        ],
        required=False,
        label='Some checklist',
        widget=forms.CheckboxSelectMultiple
    )
    
    pre_visit_note = forms.CharField(
        required=False,
        label='Pre-Visit Note',
        help_text="Visible only to visitors",
        widget=forms.Textarea()
    )

    notifications = forms.MultipleChoiceField(
        choices=[
            ('email_visitors', 'Email Visitor(s) with visit details'),
            ('email_instructor', 'Email Teacher with visit details'),
        ],
        required=False,
        label='Send Notification(s) (optional)',
        widget=forms.CheckboxSelectMultiple
    )

    def __init__(self, class_section_id, visit_id=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # get sections taught by this teacher for the same term as class_section_id
        class_section = ClassSection.objects.get(
            pk=class_section_id
        )

        sections = ClassSection.objects.filter(
            teacher=class_section.teacher,
            term=class_section.term,
            course=class_section.course
        )
        
        section_choices = []
        if sections:
            for section in sections:
                syllabi = section.syllabi_links

                section_choices.append(
                    (
                        str(section.id),
                        mark_safe(
                            f'{section.course} / {section.term} <br><span class="text-muted">Period Time: {section.period_time}</span><br>' + '<br>'.join(syllabi)
                        )
                    )
                )

        self.fields['class_sections'].choices = section_choices
        self.fields['class_sections'].initial = class_section.id

        # Visitor information
        visitors = CourseAdministrator.objects.filter(
            course=class_section.course,
            status__iexact='active'
        )

        print(class_section.course)
        print(visitors.count())

        visitor_choices = []
        for visitor in visitors:
            visitor_choices.append(
                [
                    str(visitor.user.id),
                    f"{visitor.user.last_name}, {visitor.user.first_name}"
                ]
            )
        self.fields['visitors'].choices = visitor_choices

        if not visit_id or str(visit_id) == '-1':
            self.fields['visit_id'].initial = '-1'
        else:
            visit = VisitSchedule.objects.get(
                pk=visit_id
            )

            if visit.visit_date:
                self.fields['visit_date'].initial = visit.visit_date.strftime("%m/%d/%Y")
            self.fields['visit_id'].initial = visit.id

            self.fields['pre_visit_note'].initial = visit.meta.get('pre_visit_note', '')
            self.fields['notifications'].initial = visit.meta.get('visit_notifications')

            self.fields['visitors'].initial = [
                str(visitor.id) for visitor in visit.visitors.all()
            ]
            self.fields['class_sections'].initial = [
                str(class_section.id) for class_section in visit.class_sections.all()
            ]
            
    def save(self, request, commit=False):
        data = self.cleaned_data

        if data.get('visit_id') == '-1':
            visit = VisitSchedule()
            visit.meta = {}
            
            visit.save()
        else:
            visit = VisitSchedule.objects.get(
                pk=data.get('visit_id')
            )

            visit.visit_date = None
            visit.class_sections.clear()
            visit.visitors.clear()
        
        if data.get('pre_visit_note'):
            visit.meta['pre_visit_note'] = data.get('pre_visit_note')
        
        if data.get('notifications'):
            visit.meta['visit_notifications'] = data.get('notifications')
        
        if data.get('visit_date'):
            visit.visit_date = data.get('visit_date')
            
        if data.get('class_sections'):
            class_sections = ClassSection.objects.filter(
                id__in=data.get('class_sections')
            )

            for class_section in class_sections:
                visit.class_sections.add(class_section)

        if data.get('visitors'):
            visitors = CustomUser.objects.filter(
                id__in=data.get('visitors')
            )

            for visitor in visitors:
                visit.visitors.add(visitor)

        visit.save()
        return visit

class VisitReportForm(forms.Form):
    
    visit_id = forms.CharField(
        required=True,
        widget=forms.HiddenInput()
    )
    
    created_by = forms.CharField(
        required=True,
        widget=forms.HiddenInput()
    )

    visit_report_id = forms.CharField(
        required=True,
        widget=forms.HiddenInput()
    )
    
    teacher_discussion = forms.CharField(
        required=True,
        label='Discussion with Instructor',
        widget=forms.Textarea
    )

    student_discussion = forms.CharField(
        required=True,
        label='Discussion with Students',
        widget=forms.Textarea
    )
    
    met_school_administrators = forms.MultipleChoiceField(
        choices=[],
        required=False,
        label='Did you meet any of the school administrators?',
        widget=forms.CheckboxSelectMultiple
    )

    administrator_discussion = forms.CharField(
        required=False,
        label='Discussion with Administrator(s)',
        widget=forms.Textarea
    )

    visit_letter = forms.CharField(
        required=True,
        label='Visit Letter to Instructor',
        widget=forms.Textarea
    )

    uploaded_files = forms.FileField(
        required=False,
        help_text='You can select multiple files to upload',
        widget=forms.ClearableFileInput(),
        label='Upload Files'
    )

    def __init__(self, visit, visit_report_id, created_by, *args, **kwargs):
        self.files = kwargs.pop('files', None)
        super().__init__(*args, **kwargs)

        visit_report = visit.has_report()
        if not visit_report:
            visit_report_id = -1
        else:
            visit_report_id = visit_report.id
            
            self.fields['met_school_administrators'].initial = visit_report.meta.get('met_school_administrators')
            
            self.fields['teacher_discussion'].initial = visit_report.teacher_discussion
            self.fields['student_discussion'].initial = visit_report.student_discussion
            self.fields['visit_letter'].initial = visit_report.visit_letter
            if visit_report.meta.get('visit_letter_sent_on'):
                self.fields['visit_letter'].help_text = 'Visit Letter last sent on ' + visit_report.meta.get('visit_letter_sent_on') + '. '
            
            if visit_report.status.lower() == 'submitted':
                self.fields['visit_letter'].help_text += 'Editing the current visit letter will result in another visit letter being sent.'

            self.fields['administrator_discussion'].initial = visit_report.meta.get('administrator_discussion')


        self.fields['visit_id'].initial = str(visit.id)
        self.fields['visit_report_id'].initial = visit_report_id
        self.fields['created_by'].initial = created_by.id

        self.fields['met_school_administrators'].choices = [
            ('principal', 'School Principal'),
            ('guidance', 'Guidance Counselor'),
            ('department_chair', 'Dept. Chair'),
            ('other', 'Other')
        ]

        courses = [
            class_section.course for class_section in visit.class_sections.all()
        ]
        
        course_affiliates = CourseAdministrator.objects.filter(
            course__in=courses,
            status__iexact='active'
        ).order_by(
            'user__last_name'
        )

        # cc_list = [
        #     (course_aff.user.id, f'{course_aff.user.last_name}, {course_aff.user.first_name}') for course_aff in course_affiliates
        # ]
        # self.fields['visit_letter_cc'].choices = cc_list

    def save(self, commit=True):
        data = self.cleaned_data

        report_status = 'Submitted'
        if self.data.get('submit').find('Draft') != -1:
            report_status = 'Draft'
        
        if data.get('visit_report_id') != '-1':
            visit_report = VisitReport.objects.get(
                pk=data.get('visit_report_id')
            )
        else:
            visit_report = VisitReport(
                visit_schedule=VisitSchedule.objects.get(
                    pk=data.get('visit_id')
                ),
                meta={}
            )

        visit_report.teacher_discussion = data.get('teacher_discussion')
        visit_report.student_discussion = data.get('student_discussion')
        visit_report.visit_letter = data.get('visit_letter')
        visit_report.status = report_status
        
        visit_report.meta['administrator_discussion'] = data.get('administrator_discussion')
        visit_report.meta['met_school_administrators'] = data.get('met_school_administrators')
        visit_report.meta['created_by'] = data.get('created_by')

        if commit:
            visit_report.save()

            if self.files:
                uploaded_files = self.files.getlist('uploaded_files')
                for file in uploaded_files:
                    VisitReportFile.objects.create(
                        visit_report=visit_report,
                        file=file
                    )

        return visit_report

        