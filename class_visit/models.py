import uuid, datetime
from django.conf import settings

from django.db import models
from django.db.models import JSONField
from django.urls import reverse_lazy
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from model_utils import FieldTracker

from cis.utils import (
    YES_NO_SELECT_OPTIONS,
    student_notes_media_upload_path,
    teacher_notes_media_upload_path,
    send_sms,
    model_as_HTML
)

from cis.storage_backend import PrivateMediaStorage

class VisitSchedule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    createdon = models.DateTimeField(auto_now=True)
    meta = JSONField(default=dict)

    visit_date = models.DateTimeField(blank=True, null=True)
    type_of_visit = models.CharField(max_length=200, blank=True)
    visitors = models.ManyToManyField('cis.CustomUser')
    class_sections = models.ManyToManyField('cis.ClassSection')

    def asHTML(self):
        format = [
            [
                {
                    'field': 'visit_date_sexy',
                    'label': 'Visit Date'
                },
            ],
            [
                {
                    'field': 'visitors_sexy',
                    'label': 'Visitor(s)'
                },
            ],
            [
                {
                    'field': 'visit_date_sexy',
                    'label': 'Visit Date'
                },
            ],
            [
                {
                    'field': 'highschool_sexy',
                    'label': 'High School'
                }
            ],
            [
                {
                    'field': 'instructor_sexy',
                    'label': 'Instructor'
                }
            ],
            [
                {
                    'field': 'class_sections_sexy',
                    'label': 'Class Section(s) Visited'
                },
            ],
        ]
        return model_as_HTML(self, format)

    @property
    def visit_date_sexy(self):
        if self.visit_date:
            return self.visit_date.strftime("%m/%d/%Y")
        return '-'

    def record_scheduler(self, user, via):
        """Note who scheduled the visit and from which portal (#18). Create only."""
        self.meta['scheduled_by_id'] = getattr(user, 'pk', None)
        self.meta['scheduled_by'] = user.get_full_name() if user else ''
        self.meta['scheduled_via'] = via

    @property
    def scheduled_by_display(self):
        """'Jane Doe (CE)' / 'Jane Doe (Faculty)'; '' for visits scheduled before #18."""
        meta = self.meta or {}
        name = meta.get('scheduled_by')
        if not name:
            return ''
        via = {'ce': 'CE', 'faculty': 'Faculty'}.get(meta.get('scheduled_via'), '')
        return f'{name} ({via})' if via else name

    @property
    def visitor_names(self):
        visitors = self.visitors.all()
        result = []

        for visitor in visitors:
            result.append(visitor.last_name + ', ' + visitor.first_name)

        return result

    @property
    def visitors_sexy(self):
        visitors = self.visitor_names
        return format_html_join(mark_safe('<br>'), '{}', ((v,) for v in visitors))

    @property
    def visitor_emails(self):
        visitors = self.visitors.all()
        result = []

        for visitor in visitors:
            result.append(visitor.email)

        return result

    @property
    def instructor_emails(self):
        sections = self.class_sections.all()
        result = []

        for section in sections:
            result.append(section.teacher.user.email)
            
        return result

    @property
    def instructor_sexy(self):
        sections = self.class_sections.all()

        for section in sections:
            # Only the first section is described — sections always share a teacher.
            return format_html(
                '<p>{}<br><span class="text-muted">{}</span></p>',
                section.teacher,
                section.teacher.user.email,
            )

    @property
    def teacher(self):
        """
        Return the single cis.Teacher shared by all class_sections, or None.
        Returns None if there are no sections or sections have mismatched teachers.
        """
        sections = list(self.class_sections.all())
        if not sections:
            return None
        first_teacher = sections[0].teacher
        for section in sections[1:]:
            if section.teacher.pk != first_teacher.pk:
                return None
        return first_teacher

    @property
    def instructor(self):
        """Backwards-compat alias for teacher."""
        return self.teacher

    @staticmethod
    def sections_share_teacher(class_sections_qs_or_list) -> bool:
        """
        Return True if all sections in the iterable share the same teacher.
        Returns True vacuously for empty or single-element collections.
        """
        sections = list(class_sections_qs_or_list)
        if len(sections) <= 1:
            return True
        first_pk = sections[0].teacher.pk
        return all(s.teacher.pk == first_pk for s in sections[1:])

    def ensure_confirmation_token(self):
        """
        Set meta['confirmation_token'] to a uuid4 hex string if not already set,
        then save. Returns the token string.
        """
        if not self.meta.get('confirmation_token'):
            self.meta['confirmation_token'] = uuid.uuid4().hex
            self.save(update_fields=['meta'])
        return self.meta['confirmation_token']

    @property
    def highschool_sexy(self):
        sections = self.class_sections.all()

        for section in sections:
            # Only the first section is described — sections always share a high school.
            return format_html('<p>{}</p>', section.highschool)

    @property
    def class_sections_sexy(self):
        return format_html_join(
            '',
            '<p>{} ({}/{})<br><span class="text-muted">{}</span></p>',
            (
                (
                    section.course,
                    section.class_number,
                    section.section_number,
                    section.period_time,
                )
                for section in self.class_sections.all()
            ),
        )

    def courses(self):
        sections = self.class_sections.all()
        result = []

        for section in sections:
            result.append(section.course)

        return result

    @property
    def has_started_report(self):
        return True if self.has_report() else False

    @property
    def payment_status_sexy(self):        
        report = self.has_report()
        if report:
            return report.payment_status_sexy
        return 'No report found'

    @property
    def has_submitted_report(self):
        return True if self.has_report('Submitted') else False

    def has_report(self, status=None):
        try:
            report = self.report  # OneToOne reverse accessor
            if status and report.status.lower() != status.lower():
                return False
            return report
        except VisitReport.DoesNotExist:
            return False

    @property
    def delete_url(self):
        return reverse_lazy(
            'class_visit:ce_delete_visit',
            kwargs={
                'visit_id': self.id
            }
        )

    @classmethod
    def send_pending_report_reminders(cls):
        """
        Send pending-report reminder emails to visitors for past visits that
        have no submitted report, respecting the reminder_every_days window.

        Reads settings via _get_cv_settings().

        Returns:
            (summary: str, detailed_log: dict)
              summary     — human-readable one-liner for stdout / CronLog
              detailed_log — per-visit outcome dict keyed by str(visit.pk)
        """
        cfg = _get_cv_settings()
        is_active = cfg.get('is_active', 'No')

        if is_active == 'No':
            return ('Class visit reminders inactive (is_active=No) — skipped.', {})

        reminder_every_days = cfg.get('reminder_every_days')
        if reminder_every_days is not None:
            try:
                reminder_every_days = int(reminder_every_days)
            except (ValueError, TypeError):
                reminder_every_days = None

        today = datetime.date.today()

        # Fetch past visits whose report is missing or not yet submitted.
        # We exclude visits with a submitted report at the DB level.
        past_visits = cls.objects.filter(
            visit_date__date__lte=today,
        ).exclude(
            report__status='Submitted'
        )

        sent_count = 0
        skipped_count = 0
        detailed_log = {}

        for visit in past_visits:
            if _should_remind(visit, today, reminder_every_days):
                _remind_visitor_report_pending(visit)
                detailed_log[str(visit.pk)] = 'reminded'
                sent_count += 1
            else:
                detailed_log[str(visit.pk)] = 'skipped'
                skipped_count += 1

        summary = (
            f'Visitor report reminders: {sent_count} sent, {skipped_count} skipped '
            f'(is_active={is_active}, reminder_every_days={reminder_every_days}).'
        )
        return (summary, detailed_log)


class VisitReport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    createdon = models.DateTimeField(auto_now=True)
    meta = JSONField(default=dict)

    visit_schedule = models.OneToOneField(
        'class_visit.VisitSchedule',
        on_delete=models.CASCADE,
        related_name='report',
    )
    
    teacher_discussion = models.TextField()
    student_discussion = models.TextField()
    visit_letter = models.TextField()

    tracker = FieldTracker(fields=['visit_letter', 'payment_processed'])

    STATUS_OPTIONS = (
        ('', '---'),
        ('Draft', 'Draft'),
        ('Submitted', 'Submitted'),
    )
    status = models.CharField(max_length=10, choices=STATUS_OPTIONS, default='Draft')

    payment_processed = models.CharField(
        max_length=10,
        choices=YES_NO_SELECT_OPTIONS
    )

    # Instructor sign-off (#14). Advisory throughout: none of this gates report
    # submission, status, notifications or any existing flow, and a report with
    # no sign-off stays fully valid.
    #
    # A typed attestation, matching the FERPA and student-agreement flows in cis,
    # rather than the drawn signature pad used by mou: the pad serializes only on
    # a click of `input.submit` (this form submits via fetch), and it loads from
    # a CDN the platform CSP does not allow. A CE override writes
    # 'Marked as signed by {user}', the platform-wide sentinel.
    instructor_signature = models.CharField(max_length=255, blank=True, default='')
    instructor_signed_on = models.DateTimeField(null=True, blank=True)
    instructor_response = models.TextField(blank=True, default='')
    instructor_responded_on = models.DateTimeField(null=True, blank=True)

    @property
    def is_signed_by_instructor(self):
        return bool(self.instructor_signature)

    def clear_instructor_signature(self):
        """Drop the attestation, keeping the written response.

        A signature attests to a specific version of a report, so a faculty
        re-submission invalidates it. The response is the instructor's own words
        about the visit, not a statement about a version, so it survives.
        """
        if self.instructor_signature or self.instructor_signed_on:
            self.instructor_signature = ''
            self.instructor_signed_on = None
            self.save(update_fields=['instructor_signature', 'instructor_signed_on'])


    @property
    def is_submitted(self):
        return True if self.status == 'Submitted' else False

    @property
    def is_draft(self):
        return True if self.status == 'Draft' else False

    @property
    def discussion_with_administrators(self):
        return self.meta.get('administrator_dicussion')

    @property
    def met_with_administrators(self):
        return self.meta.get('met_school_administrators')

    @property
    def met_with_administrators_sexy(self):
        if not self.meta.get('met_school_administrators'):
            return '-'
        return ','.join(self.meta.get('met_school_administrators'))

    @property
    def visit_letter_sent_on(self):
        if not self.meta['visit_letter_sent_on']:
            return '-'
        return self.meta['visit_letter_sent_on']

    def asHTML(self):
        format = [
            [
                {
                    'field': 'teacher_discussion',
                    'label': 'Discussion with Instructor'
                },
            ],
            [
                {
                    'field': 'student_discussion',
                    'label': 'Discussion with Students'
                }
            ],
            [
                {
                    'field': 'visit_letter',
                    'label': 'Visit Letter'
                }
            ],
            [
                {
                    'field': 'visit_letter_sent_on',
                    'label': 'Visit Letter Sent On'
                }
            ],
            [
                {
                    'field': 'met_with_administrators_sexy',
                    'label': 'Met with School Administrators'
                },
                {
                    'field': 'discussion_with_administrators',
                    'label': 'Discussion with Administrator(s)'
                }
            ],
            [
                {
                    'field': 'status',
                    'label': 'Report Status'
                },
                {
                    'field': 'payment_status_sexy',
                    'label': 'Payment Status'
                }
            ],
            [
                {
                    'field': 'visit_files_html',
                    'label': 'Uploaded Files'
                }
            ],
        ]
        return model_as_HTML(self, format)

    @property
    def visit_files_html(self):
        files = self.files.all()
        result = []
        from cis.utils import get_s3_url

        if not files:
            return 'No files uploaded'

        for file in files:
            result.append((get_s3_url(file.file.name), file.file.name))

        return format_html_join(
            mark_safe('<br>'),
            "<a href='{}' target='_blank'>{}</a>",
            result,
        )
    
    @property
    def payment_status_sexy(self):
        if not self.can_payment_be_processed:
            return 'Not Eligible'

        if self.payment_processed == '1':
            status = 'Processed on ' + (self.meta.get('payment_processed') or '')
            if self.payment_processed_by:
                status += ' by ' + self.payment_processed_by
            return status
        return 'Pending'

    @property
    def payment_processed_by(self):
        """Display name of whoever marked the report paid; '' for legacy rows."""
        return (self.meta or {}).get('payment_processed_by', '')

    @property
    def can_payment_be_processed(self):
        return True if self.is_submitted else False

    def _log_payment(self, action, user):
        # Append-only audit (#17): every mark / un-mark, with who and when.
        self.meta.setdefault('payment_history', []).append({
            'action': action,
            'on': datetime.datetime.now().isoformat(timespec='seconds'),
            'by_id': getattr(user, 'pk', None),
            'by': user.get_full_name() if user else '',
        })

    def mark_as_payment_processed(self, user=None):
        self.payment_processed = '1'
        self.meta['payment_processed'] = datetime.datetime.now().strftime('%m/%d/%Y')
        self.meta['payment_processed_by'] = user.get_full_name() if user else ''
        self._log_payment('paid', user)
        self.save()

    def unmark_payment_processed(self, user=None):
        """Reverse a mark-paid made in error. Returns False when the report was not paid."""
        if self.payment_processed != '1':
            return False
        self.payment_processed = '2'
        self.meta.pop('payment_processed', None)
        self.meta.pop('payment_processed_by', None)
        self._log_payment('unpaid', user)
        self.save()
        return True

class VisitReportFile(models.Model):
    FACULTY_ATTACHMENT = 'faculty_attachment'
    INSTRUCTOR_RESPONSE = 'instructor_response'
    KIND_OPTIONS = (
        (FACULTY_ATTACHMENT, 'Visitor attachment'),
        (INSTRUCTOR_RESPONSE, 'Instructor response'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    visit_report = models.ForeignKey(VisitReport, on_delete=models.CASCADE, related_name='files')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    file = models.FileField(upload_to='visit_report_files/', storage=PrivateMediaStorage())
    # Who attached it, and on whose behalf. Without these the model cannot tell a
    # visitor's evidence from an instructor's rebuttal (#14). Null keeps rows
    # created before this field loadable.
    uploaded_by = models.ForeignKey(
        'cis.CustomUser', null=True, blank=True, on_delete=models.SET_NULL)
    kind = models.CharField(
        max_length=32, choices=KIND_OPTIONS, default=FACULTY_ATTACHMENT)

    def __str__(self):
        return self.file.name


# ---------------------------------------------------------------------------
# Module-level helpers for send_pending_report_reminders
# ---------------------------------------------------------------------------

def _get_cv_settings() -> dict:
    """Thin wrapper so tests can patch without importing the settings class."""
    from .settings.class_visit import class_visit as CVSettings
    return CVSettings.from_db()


def _remind_visitor_report_pending(visit_schedule) -> None:
    """
    Thin wrapper around emails.remind_visitor_report_pending so tests can patch
    'class_visit.class_visit.models._remind_visitor_report_pending' without
    triggering circular imports.
    """
    from .services.emails import remind_visitor_report_pending
    remind_visitor_report_pending(visit_schedule)


def _should_remind(visit, today: datetime.date, reminder_every_days) -> bool:
    """
    Return True if this visit should receive a pending-report reminder today.

    Rules:
    - visit_date must be in the past (date portion <= today)
    - report must be missing or not Submitted
    - reminder_every_days days must have elapsed since meta['reminder_last_sent_on']
      (or the reminder has never been sent)
    - reminder_every_days=None behaves like 0 (remind if never sent or always due)
    """
    # Must be a past visit
    if visit.visit_date is None:
        return False
    visit_date = visit.visit_date.date() if hasattr(visit.visit_date, 'date') else visit.visit_date
    if visit_date > today:
        return False

    # Must not have a submitted report
    report = visit.has_report()
    if report and getattr(report, 'status', '') == 'Submitted':
        return False

    # Check the reminder window
    last_sent_str = visit.meta.get('reminder_last_sent_on')
    if not last_sent_str:
        return True  # never sent → always remind

    threshold = reminder_every_days if reminder_every_days is not None else 0
    try:
        last_sent = datetime.datetime.strptime(last_sent_str, '%m/%d/%Y').date()
    except (ValueError, TypeError):
        return True  # unparseable date → treat as never sent

    days_since = (today - last_sent).days
    return days_since >= threshold


class NotNeededVisit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    class_section = models.OneToOneField(
        'cis.ClassSection',
        on_delete=models.CASCADE,
        related_name='not_needed_visit',
    )
    added_by = models.ForeignKey(
        'cis.CustomUser',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'NotNeededVisit for {self.class_section}'
