"""Faculty portal views for class visit scheduling, reporting, and bulk PDF export."""
import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import require_POST
from django.urls import reverse

from rest_framework import viewsets

from cis.models.section import ClassSection
from cis.models.course import CourseAdministrator, Course
from cis.models.term import Term
from cis.utils import FACULTY_user_only, active_term as get_active_term
from cis.menu import draw_menu

from ..models import VisitSchedule, VisitReport, NotNeededVisit
from ..settings.class_visit import class_visit as ClassVisitSettings
from ..forms.faculty import VisitScheduleForm, VisitReportDynamicForm
from ..serializers.faculty import (
    FacultySchedulableSectionSerializer,
    FacultyVisitScheduleSerializer,
)
from ..services import emails, report_fields
from ..services import pdf as pdf_service

logger = logging.getLogger(__name__)


def _status_filter_to_db(section_status_filter: str):
    """Map settings value to list of ClassSection.status DB codes."""
    mapping = {
        'active': ['A'],
        'inactive': ['C'],
        'all': ['A', 'C'],
    }
    return mapping.get(section_status_filter, ['A'])


# ---------------------------------------------------------------------------
# DRF ViewSets
# ---------------------------------------------------------------------------

class FacultySchedulableSectionViewSet(viewsets.ReadOnlyModelViewSet):
    """Sections the faculty user oversees, filtered by status and not-needed."""

    serializer_class = FacultySchedulableSectionSerializer
    permission_classes = [FACULTY_user_only]

    def get_queryset(self):
        settings_obj = ClassVisitSettings.from_db()
        allowed_status_codes = _status_filter_to_db(
            settings_obj.get('section_status_filter', 'active')
        )

        course_ids = CourseAdministrator.objects.filter(
            user=self.request.user,
            status__iexact='active',
        ).values_list('course__id', flat=True)

        not_needed_section_ids = NotNeededVisit.objects.filter(
            class_section__course__id__in=course_ids,
        ).values_list('class_section__id', flat=True)

        qs = ClassSection.objects.filter(
            course__id__in=course_ids,
            status__in=allowed_status_codes,
        ).exclude(
            id__in=not_needed_section_ids,
        ).select_related(
            'teacher__user', 'course', 'term', 'highschool', 'campus', 'location',
        ).prefetch_related('visitschedule_set')

        # Optional filters from DataTables URL params
        term_id = self.request.GET.get('term_id')
        course_id = self.request.GET.get('course_id')
        if term_id:
            qs = qs.filter(term__id=term_id)
        if course_id:
            qs = qs.filter(course__id=course_id)

        return qs


class FacultyVisitScheduleViewSet(viewsets.ReadOnlyModelViewSet):
    """Visit schedules for the faculty user (visits to sections they oversee)."""

    serializer_class = FacultyVisitScheduleSerializer
    permission_classes = [FACULTY_user_only]

    def get_queryset(self):
        course_ids = CourseAdministrator.objects.filter(
            user=self.request.user,
            status__iexact='active',
        ).values_list('course__id', flat=True)

        qs = VisitSchedule.objects.filter(
            class_sections__course__id__in=course_ids,
        ).distinct().prefetch_related(
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

        term_id = self.request.GET.get('term_id')
        visitor_id = self.request.GET.get('visitor_id')
        class_section_id = self.request.GET.get('class_section_id')

        if term_id:
            qs = qs.filter(class_sections__term__id=term_id)
        if visitor_id:
            qs = qs.filter(visitors__id=visitor_id)
        if class_section_id:
            qs = qs.filter(class_sections__id=class_section_id)

        return qs


# ---------------------------------------------------------------------------
# HTML Views
# ---------------------------------------------------------------------------

@login_required(login_url='/')
@xframe_options_exempt
def manage_visit(request, class_section_id, visit_id=None):
    """Create or edit a VisitSchedule. Renders inside an iframe modal."""
    template = 'class_visit/faculty/manage_visit.html'

    visit_schedule = None
    if visit_id:
        visit_schedule = get_object_or_404(VisitSchedule, pk=visit_id)

    # The visit is anchored to the section the faculty clicked from; the section
    # options are limited to that section's course taught by the same instructor.
    anchor_section = get_object_or_404(ClassSection, pk=class_section_id)

    if request.method == 'POST':
        form = VisitScheduleForm(
            faculty_user=request.user,
            visit_schedule=visit_schedule,
            anchor_section=anchor_section,
            data=request.POST,
        )
        if form.is_valid():
            visit = form.save()
            return JsonResponse({
                'success': True,
                'message': 'Visit scheduled successfully.',
                'edit_report_url': reverse(
                    'faculty_class_visit:edit_visit_report',
                    kwargs={'visit_id': visit.id},
                ),
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'Please correct the errors below.',
                'errors': form.errors.as_json(),
            }, status=400)

    # GET
    form = VisitScheduleForm(
        faculty_user=request.user,
        visit_schedule=visit_schedule,
        anchor_section=anchor_section,
    )
    return render(request, template, {
        'form': form,
        'class_section_id': class_section_id,
        'visit_id': visit_id,
        'page_title': 'Schedule / Edit Visit',
    })


@login_required(login_url='/')
@xframe_options_exempt
def edit_visit_report(request, visit_id):
    """Write or edit a visit report. Renders inside an iframe modal."""
    template = 'class_visit/faculty/edit_visit_report.html'
    visit = get_object_or_404(VisitSchedule, pk=visit_id)

    # Load existing report meta if any
    existing_report = getattr(visit, 'report', None)
    initial_meta = existing_report.meta if existing_report else None

    if request.method == 'POST':
        form = VisitReportDynamicForm(
            visit=visit,
            initial_meta=initial_meta,
            data=request.POST,
        )
        if form.is_valid():
            report = form.save(created_by_user=request.user)
            if report.status == 'Draft':
                return JsonResponse({
                    'success': True,
                    'message': "Saved as 'Draft'.",
                    'status': 'draft',
                })
            return JsonResponse({
                'success': True,
                'message': 'Report submitted successfully.',
                'status': 'submitted',
                'action': 'reload',
            })
        else:
            return JsonResponse({
                'status': 'error',
                'message': 'Please correct the errors.',
                'errors': form.errors.as_json(),
            }, status=400)

    # GET
    form = VisitReportDynamicForm(visit=visit, initial_meta=initial_meta)
    field_defs = report_fields.get_report_field_defs()

    return render(request, template, {
        'form': form,
        'visit': visit,
        'existing_report': existing_report,
        'field_defs': field_defs,
        'page_title': 'Class Visit Report',
    })


@login_required(login_url='/')
@require_POST
def do_bulk_action(request):
    """Dispatch bulk actions on selected VisitReports.

    Supported actions:
      - export_pdf: generate a combined PDF for selected reports and return it
                    as a single application/pdf response (one pdfkit call, HTML concat).

    POST params:
      - action: str
      - ids[]: list of VisitReport UUIDs
      - public_only: '1' for public fields only, '0' for all fields
    """
    action = request.POST.get('action', '')
    raw_ids = request.POST.getlist('ids[]')
    public_only = (request.POST.get('public_only', '0') == '1')

    if action == 'export_pdf':
        # Scope to reports belonging to courses this faculty user administers (security).
        course_ids = CourseAdministrator.objects.filter(
            user=request.user, status__iexact='active'
        ).values_list('course__id', flat=True)
        reports = list(VisitReport.objects.filter(
            id__in=raw_ids,
            visit_schedule__class_sections__course__id__in=course_ids,
        ).distinct())
        if not reports:
            return JsonResponse({'success': False, 'message': 'No reports found.'}, status=404)

        # Combine all reports into a single PDF using the shared helper.
        # visit_letters_pdf concatenates inner HTML with page-breaks and makes
        # one pdfkit call — no zipfile, no per-report PDF binary merging.
        pdf_bytes = pdf_service.visit_letters_pdf(reports, public_only=public_only)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="visit-letters.pdf"'
        return response

    return JsonResponse({'success': False, 'message': f'Unknown action: {action}'}, status=400)


@login_required(login_url='/')
def delete_visit(request, visit_id):
    """Delete a VisitSchedule (only if no report exists)."""
    visit = get_object_or_404(VisitSchedule, pk=visit_id)

    if getattr(visit, 'report', None):
        return JsonResponse({
            'success': False,
            'message': 'Cannot delete a visit that already has a report.',
        })

    visit.delete()
    return JsonResponse({'success': True, 'message': 'Visit deleted.'})


@login_required(login_url='/')
def index(request):
    """Main faculty class-visits page — two DataTables tabs."""
    # Menu is pulled from the per-role `menu` setting (faculty_menu) by
    # draw_menu(); the first arg is unused. role_name='faculty' is required so
    # the faculty menu (not the default 'ce' menu) is rendered.
    menu = draw_menu(None, 'class_visits', '', 'faculty')

    course_ids = CourseAdministrator.objects.filter(
        user=request.user,
        status__iexact='active',
    ).values_list('course__id', flat=True)

    terms = Term.objects.all().order_by('-code')
    courses = Course.objects.filter(id__in=course_ids).order_by('name')
    visitors = CourseAdministrator.objects.filter(
        course__id__in=course_ids,
        status__iexact='active',
    ).select_related('user').order_by('user__last_name')

    return render(request, 'class_visit/faculty/visits.html', {
        'menu': menu,
        'terms': terms,
        'active_term': get_active_term(),
        'courses': courses,
        'visitors': visitors,
        'page_title': 'Scheduled Observations',
        'api_url': '/faculty/class_visits/api/visit_schedule/?format=datatables',
        'class_sections_api_url': '/faculty/class_visits/api/class_sections/?format=datatables',
        'payment_tracking_enabled': (
            ClassVisitSettings.from_db().get('payment_tracking', 'No') == 'Yes'
        ),
    })
