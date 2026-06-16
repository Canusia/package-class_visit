"""Faculty class-visit URL configuration.

Mounted at: faculty/class_visits/   (see myce/urls.py)
App namespace: faculty_class_visit
"""
from django.urls import path, include
from django.contrib.auth.decorators import user_passes_test
from rest_framework import routers

from cis.utils import user_has_faculty_role

from class_visit.class_visit.views.faculty import (
    FacultySchedulableSectionViewSet,
    FacultyVisitScheduleViewSet,
    index,
    manage_visit,
    edit_visit_report,
    delete_visit,
    do_bulk_action,
)

app_name = 'faculty_class_visit'

router = routers.DefaultRouter()
router.register('class_sections', FacultySchedulableSectionViewSet, basename='class_sections')
router.register('visit_schedule', FacultyVisitScheduleViewSet, basename='visit_schedule')

_guard = lambda view: user_passes_test(user_has_faculty_role, login_url='/')(view)

urlpatterns = [
    path('api/', include(router.urls)),

    path('visits/', _guard(index), name='visits'),

    path(
        'visits/manage_visit/<uuid:class_section_id>/',
        _guard(manage_visit),
        name='manage_visit',
    ),
    path(
        'visits/manage_visit/<uuid:class_section_id>/<uuid:visit_id>/',
        _guard(manage_visit),
        name='edit_visit',
    ),
    path(
        'visits/edit_visit_report/<uuid:visit_id>/',
        _guard(edit_visit_report),
        name='edit_visit_report',
    ),
    path(
        'visits/delete/<uuid:visit_id>/',
        _guard(delete_visit),
        name='delete_visit',
    ),
    path(
        'visits/bulk_action/',
        _guard(do_bulk_action),
        name='bulk_action',
    ),
]
