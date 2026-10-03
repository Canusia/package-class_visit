# class_visit/class_visit/views/instructor.py
import logging

import pdfkit

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render, get_object_or_404
from django.template.loader import get_template
from django.urls import reverse
from django.http import HttpResponse, Http404
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone

from rest_framework import viewsets

from cis.menu import draw_menu
from cis.models.teacher import Teacher
from cis.utils import INSTRUCTOR_user_only, user_has_instructor_role

from ..models import VisitSchedule, VisitReport, VisitReportFile
from ..services import emails
from ..serializers.instructor import InstructorVisitScheduleSerializer
from ..services import report_fields as rf_service
from ..services.confirmation import confirm_visit as svc_confirm
from ..services.pdf import visit_letter_pdf, visit_letters_pdf
from ..services import uploads

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _signoff_enabled():
    from ..settings.class_visit import class_visit as CVSettings
    return CVSettings.from_db().get('instructor_signature', 'No') == 'Yes'


def _get_teacher_or_none(request):
    """Return the Teacher for the logged-in user, or None."""
    try:
        return request.user.teacher
    except (Teacher.DoesNotExist, AttributeError):
        return None


# ---------------------------------------------------------------------------
# DRF viewset
# ---------------------------------------------------------------------------

class InstructorVisitScheduleViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = InstructorVisitScheduleSerializer
    permission_classes = [INSTRUCTOR_user_only]

    def get_queryset(self):
        teacher = _get_teacher_or_none(self.request)
        if teacher is None:
            return VisitSchedule.objects.none()

        return (
            VisitSchedule.objects
            .filter(class_sections__teacher=teacher)
            .prefetch_related(
                'class_sections',
                'class_sections__course',
                'class_sections__campus',
                'class_sections__highschool',
                'class_sections__location',
                'class_sections__term',
                'class_sections__registration_term',
                'class_sections__co_reqs',
                'class_sections__teacher__user',
                'visitors',
                'report',
            )
            .order_by('-visit_date')
            .distinct()
        )


# ---------------------------------------------------------------------------
# HTML views
# ---------------------------------------------------------------------------

@login_required
def index(request):
    menu = draw_menu(None, 'instructor_class_visit', '', 'instructor')
    api_url = (
        reverse('instructor_class_visit:visit-schedule-list')
        + '?format=datatables'
    )
    bulk_url = reverse('instructor_class_visit:bulk_action')
    return render(request, 'class_visit/instructor/index.html', {
        'menu': menu,
        'page_name': 'My Class Visits',
        'api_url': api_url,
        'bulk_url': bulk_url,
    })


@login_required
@xframe_options_exempt
def report_detail(request, visit_id):
    """
    Show public-only report fields for a submitted visit.
    The instructor must own at least one of the visit's class sections.
    """
    teacher = _get_teacher_or_none(request)
    if teacher is None:
        raise Http404

    visit = get_object_or_404(
        VisitSchedule.objects.filter(
            class_sections__teacher=teacher,
        ).prefetch_related(
            'visitors',
            'class_sections__course',
            'class_sections__teacher__user',
        ).distinct(),
        pk=visit_id,
    )

    # Try the OneToOne relation added by Plan 1
    report = None
    try:
        report = visit.report          # related_name='report' from Plan 1
    except Exception:
        report = None

    # Fall back to the legacy has_report() if Plan-1 relation absent
    if report is None:
        report = visit.has_report() or None

    public_values = None
    if report and report.status == 'Submitted':
        public_values = rf_service.report_values_for_display(report, public_only=True)
        if public_values is None:
            public_values = []

    ajax = request.GET.get('ajax', None)
    template = (
        'class_visit/instructor/report_detail_ajax.html' if ajax
        else 'class_visit/instructor/report_detail.html'
    )

    menu = draw_menu(None, 'instructor_class_visit', '', 'instructor')
    return render(request, template, {
        'menu': menu,
        'page_name': 'Visit Report',
        'visit': visit,
        'public_values': public_values,
        # Downloadable whenever the report is submitted — not tied to whether
        # any of its fields happen to be marked public.
        'can_download': bool(report and report.status == 'Submitted'),
        'report': report,
        # Sign-off panel: only for a submitted report, and only when the tenant
        # has opted in (#14). Advisory -- it gates nothing else on this page.
        'show_signoff': bool(
            report and report.status == 'Submitted'
            and _signoff_enabled()),
        'sign_url': reverse(
            'instructor_class_visit:sign_report', kwargs={'visit_id': visit.id}),
        'pdf_url': reverse(
            'instructor_class_visit:report_pdf', kwargs={'visit_id': visit.id}),
        'ajax': ajax,
        # Submitted reports only; visitor files only when the tenant allows it.
        'attachments': uploads.attachment_rows(report, 'instructor'),
        'signoff_file_required': uploads.instructor_file_required(),
        'signoff_has_file': bool(report) and report.files.filter(
            kind=VisitReportFile.INSTRUCTOR_RESPONSE).exists(),
        'signoff_error': (
            'Attach a file to sign or respond — your program requires one.'
            if request.GET.get('signoff_error') == 'file_required' else ''),
    })


@login_required
def download_file(request, visit_id, file_id):
    """An attachment the instructor may see on their own submitted visit report.

    404 for anything else (another instructor's visit, a draft, or a visitor
    file while `instructor_view_visitor_files` is off), so the endpoint never
    confirms what exists.
    """
    teacher = _get_teacher_or_none(request)
    if teacher is None:
        raise Http404('No file matches the given query.')
    visit = VisitSchedule.objects.filter(
        pk=visit_id, class_sections__teacher=teacher).distinct().first()
    report = visit.has_report() if visit else None
    if not report:
        raise Http404('No file matches the given query.')
    for report_file in uploads.visible_files(report, 'instructor'):
        if str(report_file.id) == str(file_id):
            return uploads.file_response(report_file)
    raise Http404('No file matches the given query.')


@login_required
def report_pdf(request, visit_id):
    """Download one visit's report as a public-only PDF letter.

    Same scoping as report_detail: the instructor must own one of the visit's
    sections, and only submitted reports are downloadable. Instructors always
    get public_only=True output, matching the bulk export.
    """
    teacher = _get_teacher_or_none(request)
    if teacher is None:
        raise Http404

    visit = get_object_or_404(
        VisitSchedule.objects.filter(class_sections__teacher=teacher).distinct(),
        pk=visit_id,
    )

    try:
        report = visit.report
    except Exception:
        report = visit.has_report() or None

    if report is None or report.status != 'Submitted':
        raise Http404

    pdf = visit_letter_pdf(report, public_only=True)
    response = HttpResponse(pdf, content_type='application/pdf')
    # visit_date_sexy is m/d/Y — the slashes are not filename-safe
    stamp = visit.visit_date_sexy.replace('/', '-')
    response['Content-Disposition'] = (
        f'attachment; filename="class_visit_report_{stamp}.pdf"'
    )
    return response


def confirm_visit_view(request, token):
    """
    Token-based confirmation link — no login required.
    Calls confirmation.confirm_visit(token); shows a simple result page.
    Idempotent: safe to visit multiple times.
    """
    visit = svc_confirm(token)   # returns VisitSchedule or None
    # NOTE: login_required = False is set below to bypass LoginRequiredMiddleware

    return render(request, 'class_visit/instructor/confirm.html', {
        'visit': visit,
        'token_valid': visit is not None,
        'page_name': 'Visit Confirmation',
    })


# Mark as public — bypass LoginRequiredMiddleware (token is the credential)
confirm_visit_view.login_required = False


@require_POST
@login_required
def sign_report(request, visit_id):
    """Record an instructor's acknowledgement of, and response to, a report (#14).

    Advisory: this never changes report status or touches the report lifecycle. A
    signature is immutable once given -- a correction is a new response, not an
    edited attestation -- and a faculty re-submission clears it
    (VisitReport.clear_instructor_signature).

    404 rather than 403 throughout, so the endpoint does not confirm which visits
    exist: for the feature being off, for another instructor's visit, and for a
    report that is not submitted yet.
    """
    from ..settings.class_visit import class_visit as CVSettings

    if CVSettings.from_db().get('instructor_signature', 'No') != 'Yes':
        raise Http404('Instructor sign-off is not enabled.')

    teacher = _get_teacher_or_none(request)
    if teacher is None:
        raise Http404('No visit matches the given query.')

    visit = VisitSchedule.objects.filter(
        pk=visit_id, class_sections__teacher=teacher).distinct().first()
    report = visit.has_report() if visit else None
    if not report or report.status != 'Submitted':
        raise Http404('No submitted report matches the given query.')

    uploaded = request.FILES.get('response_file')
    if (not uploaded and uploads.instructor_file_required()
            and not uploads.has_files(visit, VisitReportFile.INSTRUCTOR_RESPONSE)):
        # Refuse the whole post: a signature without the required file is incomplete.
        return redirect(
            reverse('instructor_class_visit:report_detail', kwargs={'visit_id': visit.id})
            + '?signoff_error=file_required')

    now = timezone.now()
    fields = []

    signature = (request.POST.get('instructor_signature') or '').strip()
    if signature and not report.instructor_signature:
        report.instructor_signature = signature[:255]
        report.instructor_signed_on = now
        fields += ['instructor_signature', 'instructor_signed_on']

    response_text = (request.POST.get('instructor_response') or '').strip()
    if response_text:
        report.instructor_response = response_text
        report.instructor_responded_on = now
        fields += ['instructor_response', 'instructor_responded_on']

    if fields:
        report.save(update_fields=fields)

    if uploaded:
        VisitReportFile.objects.create(
            visit_report=report, file=uploaded, uploaded_by=request.user,
            kind=VisitReportFile.INSTRUCTOR_RESPONSE)

    if response_text or uploaded:
        emails.notify_visitor_instructor_responded(report)

    return redirect('instructor_class_visit:report_detail', visit_id=visit.id)


@require_POST
@login_required
def do_bulk_action(request):
    """
    POST: action=export_pdf, ids[]=<uuid>, ids[]=<uuid>, ...
    Returns a combined public-only PDF for all selected submitted visits
    that belong to the logged-in instructor, as a single application/pdf response.

    Non-submitted visits and visits not belonging to this instructor are skipped.
    Uses pdf.visit_letters_pdf (HTML-concat, one pdfkit call — no pypdf, no zipfile).
    Instructors always receive public_only=True output.
    """
    teacher = _get_teacher_or_none(request)
    if teacher is None:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()

    ids = request.POST.getlist('ids[]')

    # Scope to this instructor's own visits only (security: never trust client IDs)
    visits = (
        VisitSchedule.objects
        .filter(
            pk__in=ids,
            class_sections__teacher=teacher,
        )
        .distinct()
        .prefetch_related('class_sections', 'visitors')
    )

    # Collect submitted reports only; skip non-submitted or missing
    submitted_reports = []
    for visit in visits:
        try:
            report = visit.report
        except Exception:
            report = visit.has_report() or None

        if report is None or report.status != 'Submitted':
            continue
        submitted_reports.append(report)

    if not submitted_reports:
        fallback_body = '<p>No submitted visit reports found for the selected visits.</p>'
        fallback_html = get_template('cis/print_base.html').render({'main_content': fallback_body})
        combined_pdf = pdfkit.from_string(fallback_html, False, {'page-size': 'Letter'})
    else:
        # Single pdfkit call via shared helper — HTML concat, no pypdf, no zipfile
        combined_pdf = visit_letters_pdf(submitted_reports, public_only=True)

    response = HttpResponse(combined_pdf, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="class_visit_letters.pdf"'
    return response
