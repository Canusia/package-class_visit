"""CE Staff views and DRF viewsets for class visits."""
import logging

from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import require_POST

from rest_framework import viewsets

from cis.menu import draw_menu
from cis.models.course import Course
from cis.models.section import ClassSection
from cis.models.term import Term
from cis.utils import CIS_user_only, active_term, user_has_cis_role

from ..forms.ce import CEVisitScheduleForm
from ..models import NotNeededVisit, VisitReport, VisitSchedule
from ..serializers.ce import (
    CENotNeededVisitSerializer,
    CEVisitScheduleSerializer,
)
from ..services import pdf as pdf_service
from ..services import report_fields

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DRF ViewSets
# ---------------------------------------------------------------------------

class CEVisitScheduleViewSet(viewsets.ReadOnlyModelViewSet):
    """Server-side DataTables viewset for all scheduled visits (CE only)."""

    serializer_class = CEVisitScheduleSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        qs = VisitSchedule.objects.all().distinct().prefetch_related(
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

        term_id = self.request.GET.get('term_id')
        course_id = self.request.GET.get('course_id')
        visitor_id = self.request.GET.get('visitor_id')
        teacher_id = self.request.GET.get('teacher_id')
        highschool_id = self.request.GET.get('highschool_id')
        report_status = self.request.GET.get('report_status')

        if term_id:
            qs = qs.filter(class_sections__term__id=term_id)
        if course_id:
            if course_id == '-2':
                course_ids = self.request.user.get_courses_overseeing()
                qs = qs.filter(class_sections__course__id__in=course_ids)
            else:
                qs = qs.filter(class_sections__course__id=course_id)
        if visitor_id:
            qs = qs.filter(visitors__id=visitor_id)
        if teacher_id:
            qs = qs.filter(class_sections__teacher__id=teacher_id)
        if highschool_id:
            qs = qs.filter(class_sections__highschool__id=highschool_id)
        if report_status:
            if report_status == 'no_report':
                qs = qs.filter(report__isnull=True)
            else:
                qs = qs.filter(report__status__iexact=report_status)

        return qs.order_by('-visit_date')


class CENotNeededVisitViewSet(viewsets.ReadOnlyModelViewSet):
    """Server-side DataTables viewset for not-needed visits (CE only)."""

    serializer_class = CENotNeededVisitSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        qs = NotNeededVisit.objects.select_related(
            'class_section', 'class_section__course',
            'class_section__highschool', 'class_section__teacher',
            'added_by',
        ).all()

        term_id = self.request.GET.get('term_id')
        course_id = self.request.GET.get('course_id')

        if term_id:
            qs = qs.filter(class_section__term__id=term_id)
        if course_id:
            qs = qs.filter(class_section__course__id=course_id)

        return qs.order_by('-created_at')


# ---------------------------------------------------------------------------
# Page views
# ---------------------------------------------------------------------------

@login_required(login_url='/')
def index(request):
    """Main CE class visits page — multi-tab DataTable."""
    menu = draw_menu(None, 'classes', 'class_visits', 'ce')
    return render(
        request,
        'class_visit/ce/index.html',
        {
            'menu': menu,
            'page_title': 'Class Visits / Reports',
            'terms': Term.objects.all().order_by('code'),
            'courses': Course.objects.filter(status__iexact='active').order_by('name'),
            'active_term': active_term(),
            'api_url': '/ce/class_visits/api/visit_schedule/?format=datatables',
            'not_needed_api_url': '/ce/class_visits/api/not_needed_visit/?format=datatables',
        },
    )


# ---------------------------------------------------------------------------
# Visit CRUD (modal/iframe pattern)
# ---------------------------------------------------------------------------

@login_required(login_url='/')
@xframe_options_exempt
def manage_visit(request, section_id=None, visit_id=None):
    """Add (section_id required) or edit (visit_id required) a VisitSchedule."""
    # For edit without a section_id, derive it from the first section on the visit.
    if visit_id and not section_id:
        visit = get_object_or_404(VisitSchedule, pk=visit_id)
        first_section = visit.class_sections.first()
        if first_section:
            section_id = first_section.id

    form = CEVisitScheduleForm(section_id=section_id, visit_id=visit_id)

    if request.method == 'POST':
        form = CEVisitScheduleForm(
            section_id=section_id,
            visit_id=visit_id,
            data=request.POST,
        )
        if form.is_valid():
            form.save(request=request, commit=True)
            return JsonResponse({'success': True, 'message': 'Visit saved successfully.'})
        else:
            return JsonResponse(
                {
                    'success': False,
                    'message': 'Please fix the errors below.',
                    'errors': str(form.errors),
                }
            )

    return render(
        request,
        'class_visit/ce/manage_visit.html',
        {
            'page_title': 'Manage Visit Schedule',
            'form': form,
            'section_id': section_id,
            'visit_id': visit_id or '-1',
        },
    )


@login_required(login_url='/')
def delete_visit(request, visit_id):
    """Delete a VisitSchedule. Blocks deletion if a report exists."""
    visit = get_object_or_404(VisitSchedule, pk=visit_id)

    try:
        _ = visit.report
        return JsonResponse(
            {
                'success': False,
                'message': 'Cannot delete: a visit report has already been started. '
                           'Delete the report first.',
            }
        )
    except VisitReport.DoesNotExist:
        pass
    except AttributeError:
        pass

    visit.delete()
    return JsonResponse({'success': True, 'message': 'Visit deleted successfully.'})


# ---------------------------------------------------------------------------
# Full report view (CE sees public_only=False)
# ---------------------------------------------------------------------------

@login_required(login_url='/')
def view_report(request, visit_id):
    """CE full report view — all report fields regardless of public flag."""
    visit = get_object_or_404(VisitSchedule, pk=visit_id)
    try:
        report = visit.report
    except Exception:
        report = None

    fields = []
    if report:
        fields = report_fields.report_values_for_display(report, public_only=False)

    return render(
        request,
        'class_visit/ce/view_report.html',
        {
            'menu': draw_menu(None, 'classes', 'class_visits', 'ce'),
            'page_title': 'Class Visit Report',
            'visit': visit,
            'report': report,
            'report_fields': fields,
        },
    )


# ---------------------------------------------------------------------------
# Not-Needed visit management
# ---------------------------------------------------------------------------

@login_required(login_url='/')
def not_needed_add(request):
    """Add a ClassSection to the not-needed-visit list (POST: class_section_id)."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'POST required.'}, status=405)

    section_id = request.POST.get('class_section_id')
    if not section_id:
        return JsonResponse({'success': False, 'message': 'class_section_id required.'}, status=400)

    section = get_object_or_404(ClassSection, pk=section_id)

    obj, created = NotNeededVisit.objects.get_or_create(
        class_section=section,
        defaults={'added_by': request.user},
    )

    if created:
        return JsonResponse({'success': True, 'message': 'Section marked as not-needed.'})
    return JsonResponse(
        {'success': False, 'message': 'This section is already in the not-needed list.'}
    )


@login_required(login_url='/')
def not_needed_remove(request, pk):
    """Remove a NotNeededVisit row."""
    obj = get_object_or_404(NotNeededVisit, pk=pk)
    obj.delete()
    return JsonResponse({'success': True, 'message': 'Removed from not-needed list.'})


@login_required(login_url='/')
@xframe_options_exempt
def not_needed_picker(request):
    """Iframe modal: pick a ClassSection to add to the not-needed list."""
    term_id = request.GET.get('term_id')
    course_id = request.GET.get('course_id')

    sections = ClassSection.objects.exclude(
        not_needed_visit__isnull=False
    ).select_related('course', 'teacher', 'highschool', 'term')

    if term_id:
        sections = sections.filter(term__id=term_id)
    if course_id:
        sections = sections.filter(course__id=course_id)

    sections = sections.order_by('course__name', 'teacher__user__last_name')[:200]

    return render(
        request,
        'class_visit/ce/not_needed/add_section.html',
        {
            'page_title': 'Add to Not-Needed List',
            'sections': sections,
            'terms': Term.objects.all().order_by('code'),
            'courses': Course.objects.filter(status__iexact='active').order_by('name'),
        },
    )


# ---------------------------------------------------------------------------
# Bulk action: export visit letters as combined PDF
# ---------------------------------------------------------------------------

@login_required(login_url='/')
@require_POST
def do_bulk_action(request):
    """Bulk action handler for the CE visits DataTable.

    POST body:
        ids[]         — list of VisitSchedule UUIDs
        public_only   — '1' → public fields only; '0' (default) → all fields
        action        — currently only 'export_pdf' is supported
    """
    action = request.POST.get('action', 'export_pdf')
    ids = request.POST.getlist('ids[]')
    public_only = request.POST.get('public_only', '0') == '1'

    if not ids:
        return JsonResponse({'success': False, 'message': 'No visits selected.'}, status=400)

    if action == 'export_pdf':
        reports = []
        for visit_id in ids:
            try:
                visit = VisitSchedule.objects.get(pk=visit_id)
                reports.append(visit.report)
            except (VisitSchedule.DoesNotExist, VisitReport.DoesNotExist):
                continue  # skip missing visits or visits with no report

        if not reports:
            return JsonResponse(
                {'success': False, 'message': 'No reports found for selected visits.'},
                status=400,
            )

        pdf_bytes = pdf_service.visit_letters_pdf(reports, public_only=public_only)

        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="visit_letters.pdf"'
        return response

    return JsonResponse({'success': False, 'message': f'Unknown action: {action}'}, status=400)
