import json

from django import forms
from django.http import JsonResponse
from django.urls import reverse_lazy

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.models.settings import Setting


class class_visit(forms.Form):
    """
    Settings for the Class Visit feature.

    Stored as a single Setting row with key='class_visit'.

    report_fields_json shape:
        [
          {
            "name": "field_name",
            "label": "Human Label",
            "type": "text|textarea|select|checkbox|date",
            "public": true,
            "required": false,
            "options": ["Opt A", "Opt B"]   // for select type only
          },
          ...
        ]
    """

    key = 'class_visit'

    STATUS_OPTIONS = [
        ('', 'Select'),
        ('Yes', 'Yes'),
        ('No', 'No'),
        ('Debug', 'Debug'),
    ]

    YES_NO = [
        ('Yes', 'Yes'),
        ('No', 'No'),
    ]

    # ---- General ----
    is_active = forms.ChoiceField(
        choices=STATUS_OPTIONS,
        label='Email Status',
        help_text='Yes=send live emails; Debug=redirect to debug_email_list; No=suppress all.',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}),
    )

    debug_email_list = forms.CharField(
        max_length=500,
        required=False,
        help_text='Comma-separated email addresses. Used when is_active=Debug.',
        label='Debug Email List',
    )

    payment_tracking = forms.ChoiceField(
        choices=YES_NO,
        label='Payment Tracking',
        help_text='When Yes, CE staff can mark submitted visit reports as paid.',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}),
    )

    # ---- Report field configuration ----
    report_fields_json = forms.CharField(
        required=False,
        widget=forms.Textarea,
        label='Report Fields (JSON)',
        help_text=(
            'JSON array of field definitions. Each object: '
            '{"name":"field_name","label":"Label","type":"text|textarea|select|checkbox|date",'
            '"public":true,"required":false,"options":["A","B"]}. '
            '"options" is only used when type=select.'
        ),
    )

    # ---- Visit types ----
    visit_types = forms.CharField(
        max_length=500,
        required=False,
        label='Visit Types',
        help_text='Pipe-delimited list of visit types. E.g. Initial|Follow-up|Annual',
    )

    # ---- Section status filter ----
    section_status_filter = forms.ChoiceField(
        choices=[
            ('active', 'Active (status=A)'),
            ('inactive', 'Inactive (status=C)'),
            ('all', 'All'),
        ],
        label='Section Status Filter',
        help_text='Which class sections are shown when scheduling a visit.',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}),
    )

    # ---- Notification target ----
    notify_target = forms.ChoiceField(
        choices=[
            ('course_administrator', 'Course Administrator'),
            ('generic_email', 'Generic Email'),
        ],
        label='Notify On Report Submit',
        help_text='Who receives the notification when a visit report is submitted.',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}),
    )

    generic_email = forms.EmailField(
        required=False,
        label='Generic Notification Email',
        help_text='Used when Notify Target = Generic Email.',
    )

    # ---- Teacher notification on schedule ----
    notify_teacher_on_schedule = forms.ChoiceField(
        choices=YES_NO,
        label='Notify Teacher When Visit Scheduled',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}),
    )

    teacher_scheduled_subject = forms.CharField(
        max_length=500,
        required=False,
        label='Teacher Scheduled Email Subject',
    )

    teacher_scheduled_message = forms.CharField(
        required=False,
        widget=forms.Textarea,
        label='Teacher Scheduled Email Message',
        help_text=(
            'Shortcodes: {{teacher_first_name}}, {{teacher_last_name}}, {{visit_date}}, '
            '{{visitors}}, {{class_sections}}, {{type_of_visit}}, {{pre_visit_note}}, '
            '{{confirmation_link}}'
        ),
    )

    # ---- Instructor confirmation link ----
    instructor_confirm_link = forms.ChoiceField(
        choices=YES_NO,
        label='Include Instructor Confirmation Link',
        help_text='When Yes, a confirmation link is appended to the teacher notification.',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}),
    )

    # ---- Teacher notification on submit ----
    notify_teacher_on_submit = forms.ChoiceField(
        choices=YES_NO,
        label='Notify Teacher When Report Submitted',
        widget=forms.Select(attrs={'class': 'col-md-4 col-sm-12'}),
    )

    teacher_submit_subject = forms.CharField(
        max_length=500,
        required=False,
        label='Teacher Submit Notification Subject',
    )

    teacher_submit_message = forms.CharField(
        required=False,
        widget=forms.Textarea,
        label='Teacher Submit Notification Message',
        help_text=(
            'Shortcodes: {{teacher_first_name}}, {{teacher_last_name}}, '
            '{{visit_date}}, {{public_report_url}}'
        ),
    )

    # ---- Visitor reminder ----
    visitor_reminder_subject = forms.CharField(
        max_length=500,
        required=False,
        label='Visitor Reminder Email Subject',
    )

    visitor_reminder_message = forms.CharField(
        required=False,
        widget=forms.Textarea,
        label='Visitor Reminder Email Message',
        help_text=(
            'Shortcodes: {{visitor_first_name}}, {{visit_date}}, '
            '{{class_sections}}, {{report_url}}'
        ),
    )

    reminder_every_days = forms.IntegerField(
        initial=7,
        required=False,
        label='Send Visitor Reminder Every N Days',
        help_text='Number of days between visitor reminder emails. Default: 7.',
    )

    # ------------------------------------------------------------------
    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if request is not None:
            self.request = request
            self.helper = FormHelper()
            self.helper.attrs = {'target': '_blank'}
            self.helper.form_method = 'POST'
            self.helper.form_action = reverse_lazy(
                'setting:run_record',
                args=[request.GET.get('report_id')],
            )
            self.helper.add_input(Submit('submit', 'Save Setting'))

    @classmethod
    def from_db(cls):
        """Return the stored settings dict, or {} if not yet installed."""
        try:
            setting = Setting.objects.get(key=cls.key)
            return setting.value
        except Setting.DoesNotExist:
            return {}

    def install(self):
        """Create the Setting row with safe defaults if it does not exist."""
        defaults = {
            'is_active': 'No',
            'debug_email_list': '',
            'payment_tracking': 'No',
            'report_fields_json': '[]',
            'visit_types': 'Initial|Follow-up|Annual',
            'section_status_filter': 'active',
            'notify_target': 'course_administrator',
            'generic_email': '',
            'notify_teacher_on_schedule': 'No',
            'teacher_scheduled_subject': 'Class Visit Scheduled',
            'teacher_scheduled_message': '',
            'instructor_confirm_link': 'No',
            'notify_teacher_on_submit': 'No',
            'teacher_submit_subject': 'Class Visit Report Submitted',
            'teacher_submit_message': '',
            'visitor_reminder_subject': 'Class Visit Reminder',
            'visitor_reminder_message': '',
            'reminder_every_days': 7,
        }
        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        setting.value = defaults
        setting.save()

    def _to_python(self):
        """Return cleaned form data as a plain dict for storage."""
        result = {}
        for key, value in self.cleaned_data.items():
            result[key] = value
        return result

    def run_record(self):
        """Save POSTed form data to the Setting row and return JSON response."""
        try:
            setting = Setting.objects.get(key=self.key)
        except Setting.DoesNotExist:
            setting = Setting()
            setting.key = self.key

        setting.value = self._to_python()
        setting.save()

        return JsonResponse({
            'message': 'Successfully saved settings',
            'status': 'success',
        })
