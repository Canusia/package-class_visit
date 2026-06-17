"""CE Staff URL configuration for class_visit submodule.

Mounts at: ce/class_visits/  (wired in host app's myce/urls.py)
App namespace: class_visit
"""
from django.urls import path, include
from django.contrib.auth.decorators import user_passes_test

from rest_framework.routers import DefaultRouter

from cis.utils import user_has_cis_role

from ..views.ce import (
    CEVisitScheduleViewSet,
    CENotNeededVisitViewSet,
    index,
    manage_visit,
    delete_visit,
    view_report,
    not_needed_add,
    not_needed_remove,
    not_needed_picker,
    do_bulk_action,
)

app_name = 'class_visit'

router = DefaultRouter()
router.register('visit_schedule', CEVisitScheduleViewSet, basename='visit_schedule')
router.register('not_needed_visit', CENotNeededVisitViewSet, basename='not_needed_visit')

_ce = user_passes_test(user_has_cis_role, login_url='/')

urlpatterns = [
    # DRF API (server-side DataTables + REST detail)
    path('api/', include(router.urls)),

    # Main page
    path(
        '',
        _ce(index),
        name='ce_index',
    ),

    # Visit CRUD
    path(
        'manage/<uuid:section_id>/',
        _ce(manage_visit),
        name='ce_manage_visit',
    ),
    path(
        'edit/<uuid:visit_id>/',
        _ce(manage_visit),
        name='ce_edit_visit',
    ),
    path(
        'delete/<uuid:visit_id>/',
        _ce(delete_visit),
        name='ce_delete_visit',
    ),

    # Full report view
    path(
        'report/<uuid:visit_id>/',
        _ce(view_report),
        name='ce_view_report',
    ),

    # Not-needed visit management
    path(
        'not-needed/add/',
        _ce(not_needed_add),
        name='ce_not_needed_add',
    ),
    path(
        'not-needed/remove/<uuid:pk>/',
        _ce(not_needed_remove),
        name='ce_not_needed_remove',
    ),
    path(
        'not-needed/picker/',
        _ce(not_needed_picker),
        name='ce_not_needed_picker',
    ),

    # Bulk actions
    path(
        'bulk-action/',
        _ce(do_bulk_action),
        name='ce_bulk_action',
    ),
]
