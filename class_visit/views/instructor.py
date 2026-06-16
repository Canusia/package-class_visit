# class_visit/class_visit/views/instructor.py
import logging

import pdfkit

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.template.loader import get_template
from django.urls import reverse
from django.http import HttpResponse, Http404
from django.views.decorators.http import require_POST

from rest_framework import viewsets

from cis.menu import draw_menu
from cis.models.teacher import Teacher
from cis.utils import INSTRUCTOR_user_only, user_has_instructor_role

from ..models import VisitSchedule, VisitReport
from ..serializers.instructor import InstructorVisitScheduleSerializer
from ..services import report_fields as rf_service
from ..services.confirmation import confirm_visit as svc_confirm
from ..services.pdf import visit_letters_pdf

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
                'class_sections__syllabi',
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
def report_detail(request, visit_id):
    """
    Show public-only report fields for a submitted visit.
    The instructor must own at least one of the visit's class sections.
    """
    teacher = _get_teacher_or_none(request)
    if teacher is None:
        raise Http404

    visit = get_object_or_404(
        VisitSchedule.objects.filter(class_sections__teacher=teacher).distinct(),
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

    menu = draw_menu(None, 'instructor_class_visit', '', 'instructor')
    return render(request, 'class_visit/instructor/report_detail.html', {
        'menu': menu,
        'page_name': 'Visit Report',
        'visit': visit,
        'public_values': public_values,
    })


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
