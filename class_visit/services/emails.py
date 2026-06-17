"""
Email service functions for class_visit.

All email sending goes through send_app_email() which handles Debug/Yes/No modes
and renders the cis/email.html wrapper template.
"""
import datetime

from django.conf import settings
from django.template.loader import render_to_string
from django.template import Context, Template

from mailer import send_html_mail


def _get_settings() -> dict:
    """Thin wrapper so tests can patch without importing the class."""
    from ..settings.class_visit import class_visit as CVSettings
    return CVSettings.from_db()


def render_template(text: str, ctx: dict) -> str:
    """
    Render a Django template string with the given context dict.
    Missing variables render as empty string (Django default).
    """
    return Template(text).render(Context(ctx))


def send_app_email(subject: str, message_text: str, recipients: list) -> None:
    """
    Send an HTML email wrapped in cis/email.html.

    Behavior:
      - is_active == 'No'    → suppress (return early)
      - is_active == 'Debug' → redirect to debug_email_list
      - is_active == 'Yes'   → send to recipients
      - settings.DEBUG == True → always redirect to debug list

    Args:
        subject: email subject line.
        message_text: plain-text/HTML body (rendered before passing in).
        recipients: list of email address strings.
    """
    cfg = _get_settings()
    is_active = cfg.get('is_active', 'No')

    if is_active == 'No':
        return

    html_body = render_to_string('cis/email.html', {'message': message_text})

    to = recipients
    if is_active == 'Debug' or getattr(settings, 'DEBUG', False):
        raw_debug = cfg.get('debug_email_list', '')
        to = [e.strip() for e in raw_debug.split(',') if e.strip()]
        if not to:
            return  # debug list is empty — suppress

    send_html_mail(
        subject,
        message_text,
        html_body,
        settings.DEFAULT_FROM_EMAIL,
        to,
    )


def notify_teacher_visit_scheduled(visit_schedule) -> None:
    """
    Send the 'visit scheduled' notification to the teacher/instructor.

    Records meta['instructor_email_sent_on'] on the visit_schedule.
    Skips if notify_teacher_on_schedule != 'Yes'.
    Appends confirmation link if instructor_confirm_link == 'Yes'.
    """
    cfg = _get_settings()
    if cfg.get('notify_teacher_on_schedule', 'No') != 'Yes':
        return

    teacher = visit_schedule.teacher
    if not teacher:
        return

    confirm_link = ''
    if cfg.get('instructor_confirm_link', 'No') == 'Yes':
        from ..services.confirmation import confirmation_url
        confirm_link = confirmation_url(visit_schedule)

    ctx = {
        'teacher_first_name': teacher.user.first_name,
        'teacher_last_name': teacher.user.last_name,
        'visit_date': visit_schedule.visit_date_sexy,
        'visitors': ', '.join(visit_schedule.visitor_names),
        'class_sections': visit_schedule.class_sections_sexy,
        'type_of_visit': visit_schedule.type_of_visit,
        'pre_visit_note': visit_schedule.meta.get('pre_visit_note', ''),
        'confirmation_link': confirm_link,
    }

    subject = cfg.get('teacher_scheduled_subject', '')
    message = render_template(cfg.get('teacher_scheduled_message', ''), ctx)

    send_app_email(subject, message, visit_schedule.instructor_emails)

    # Record sent timestamp
    from ..models import VisitSchedule
    VisitSchedule.objects.filter(pk=visit_schedule.pk).update(
        meta={**visit_schedule.meta, 'instructor_email_sent_on': datetime.datetime.now().strftime('%m/%d/%Y')}
    )


def notify_teacher_report_submitted(visit_report) -> None:
    """
    Notify the teacher when their visit report is submitted.

    Records nothing in meta (the caller/signal handles that).
    Skips if notify_teacher_on_submit != 'Yes'.
    """
    cfg = _get_settings()
    if cfg.get('notify_teacher_on_submit', 'No') != 'Yes':
        return

    visit_schedule = visit_report.visit_schedule
    teacher = visit_schedule.teacher
    if not teacher:
        return

    ctx = {
        'teacher_first_name': teacher.user.first_name,
        'teacher_last_name': teacher.user.last_name,
        'visit_date': visit_schedule.visit_date_sexy,
        'public_report_url': '',  # Plans 2/4 will populate this via a view URL
    }

    subject = cfg.get('teacher_submit_subject', '')
    message = render_template(cfg.get('teacher_submit_message', ''), ctx)

    send_app_email(subject, message, visit_schedule.instructor_emails)


def notify_notification_target(visit_report) -> None:
    """
    Notify either the course administrator or the generic email when a report is submitted.

    The target is determined by settings.notify_target:
      - 'course_administrator' → CourseAdministrator with role iexact 'administrator'
                                 for any course linked to the visit's sections.
      - 'generic_email'       → settings.generic_email

    Records meta['course_admin_email_sent_on'] on the VisitReport.
    """
    cfg = _get_settings()
    notify_target = cfg.get('notify_target', 'course_administrator')

    visit_schedule = visit_report.visit_schedule
    teacher = visit_schedule.teacher

    ctx = {
        'teacher_first_name': teacher.user.first_name if teacher else '',
        'teacher_last_name': teacher.user.last_name if teacher else '',
        'visit_date': visit_schedule.visit_date_sexy,
        'class_sections': visit_schedule.class_sections_sexy,
    }

    if notify_target == 'course_administrator':
        from cis.models.course import CourseAdministrator
        courses = visit_schedule.courses()
        course_admins = CourseAdministrator.objects.filter(
            course__in=courses,
            status__iexact='active',
            role__iexact='administrator',
        )
        recipients = [ca.user.email for ca in course_admins if ca.user.email]
    else:
        generic = cfg.get('generic_email', '').strip()
        recipients = [generic] if generic else []

    if not recipients:
        return

    subject = cfg.get('teacher_submit_subject', 'Visit Report Submitted')
    message = render_template(cfg.get('teacher_submit_message', ''), ctx)
    send_app_email(subject, message, recipients)

    # Record sent timestamp
    from ..models import VisitReport
    VisitReport.objects.filter(pk=visit_report.pk).update(
        meta={**visit_report.meta, 'course_admin_email_sent_on': datetime.datetime.now().strftime('%m/%d/%Y')}
    )


def remind_visitor_report_pending(visit_schedule) -> None:
    """
    Send a reminder email to each visitor for a visit whose report is not yet submitted.

    Records meta['reminder_last_sent_on'] on the visit_schedule.
    """
    cfg = _get_settings()
    subject = cfg.get('visitor_reminder_subject', '')
    message_template = cfg.get('visitor_reminder_message', '')

    recipients = []
    for visitor in visit_schedule.visitors.all():
        ctx = {
            'visitor_first_name': visitor.first_name,
            'visit_date': visit_schedule.visit_date_sexy,
            'class_sections': visit_schedule.class_sections_sexy,
            'report_url': '',  # Plans 2/4 will supply this via a view URL
        }
        message = render_template(message_template, ctx)
        send_app_email(subject, message, [visitor.email])
        recipients.append(visitor.email)

    if recipients:
        from ..models import VisitSchedule
        VisitSchedule.objects.filter(pk=visit_schedule.pk).update(
            meta={**visit_schedule.meta, 'reminder_last_sent_on': datetime.datetime.now().strftime('%m/%d/%Y')}
        )
