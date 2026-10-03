# class_visit/class_visit/urls/instructor.py
from django.urls import path, include
from django.contrib.auth.decorators import user_passes_test

from rest_framework import routers

from cis.utils import user_has_instructor_role

from ..views.instructor import (
    index,
    report_detail,
    report_pdf,
    confirm_visit_view,
    InstructorVisitScheduleViewSet,
    do_bulk_action,
    sign_report,
    download_file,
)

app_name = 'instructor_class_visit'

router = routers.DefaultRouter()
router.register('visit-schedule', InstructorVisitScheduleViewSet, basename='visit-schedule')

_guard = lambda view: user_passes_test(user_has_instructor_role, login_url='/')(view)

urlpatterns = [
    path('api/', include(router.urls)),

    path(
        '',
        _guard(index),
        name='index',
    ),
    path(
        'report/<uuid:visit_id>/',
        _guard(report_detail),
        name='report_detail',
    ),
    path(
        'report/<uuid:visit_id>/pdf/',
        _guard(report_pdf),
        name='report_pdf',
    ),
    path(
        'report/<uuid:visit_id>/sign/',
        _guard(sign_report),
        name='sign_report',
    ),
    path(
        'report/<uuid:visit_id>/files/<uuid:file_id>/',
        _guard(download_file),
        name='download_file',
    ),
    path(
        'confirm/<str:token>/',
        confirm_visit_view,      # deliberately no role guard — token is the auth
        name='confirm_visit',
    ),
    path(
        'bulk/',
        _guard(do_bulk_action),
        name='bulk_action',
    ),
]
