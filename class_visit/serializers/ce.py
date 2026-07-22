"""CE-facing serializers for class visit DataTables."""
from rest_framework import serializers
from django.urls import reverse

from cis.serializers.class_section import ClassSectionSerializer
from cis.serializers.highschool_admin import CustomUserSerializer

from ..models import VisitSchedule, NotNeededVisit


class CEVisitScheduleSerializer(serializers.ModelSerializer):
    """Serializer for the CE all-visits DataTable."""

    class_sections = ClassSectionSerializer(many=True, read_only=True)
    visitors = CustomUserSerializer(many=True, read_only=True)

    visit_date = serializers.DateTimeField(format='%m/%d/%Y', allow_null=True)
    type_of_visit = serializers.CharField(default='')

    # Computed display fields
    teacher_display = serializers.SerializerMethodField()
    report_status = serializers.SerializerMethodField()
    ce_edit_url = serializers.SerializerMethodField()
    ce_delete_url = serializers.SerializerMethodField()
    ce_report_url = serializers.SerializerMethodField()
    payment_status = serializers.SerializerMethodField()

    def get_payment_status(self, obj):
        try:
            return obj.report.payment_status_sexy
        except Exception:
            return ''

    def get_teacher_display(self, obj):
        teacher = obj.teacher
        if teacher is None:
            return ''
        try:
            return f"{teacher.user.last_name}, {teacher.user.first_name}"
        except Exception:
            return ''

    def get_report_status(self, obj):
        try:
            return obj.report.status
        except Exception:
            return 'No Report'

    def get_ce_edit_url(self, obj):
        try:
            return reverse(
                'class_visit:ce_edit_visit',
                kwargs={'visit_id': obj.id}
            )
        except Exception:
            return '#'

    def get_ce_delete_url(self, obj):
        try:
            return reverse(
                'class_visit:ce_delete_visit',
                kwargs={'visit_id': obj.id}
            )
        except Exception:
            return '#'

    def get_ce_report_url(self, obj):
        try:
            obj.report  # triggers RelatedObjectDoesNotExist if missing
            return reverse(
                'class_visit:ce_view_report',
                kwargs={'visit_id': obj.id}
            )
        except Exception:
            return ''

    class Meta:
        model = VisitSchedule
        fields = [
            'id',
            'visit_date',
            'type_of_visit',
            'class_sections',
            'visitors',
            'teacher_display',
            'report_status',
            'ce_edit_url',
            'ce_delete_url',
            'ce_report_url',
            'payment_status',
            'meta',
        ]
        datatables_always_serialize = [
            'id',
            'visit_date',
            'type_of_visit',
            'class_sections',
            'visitors',
            'teacher_display',
            'report_status',
            'ce_edit_url',
            'ce_delete_url',
            'ce_report_url',
            'payment_status',
        ]


class CENotNeededVisitSerializer(serializers.ModelSerializer):
    """Serializer for the CE not-needed-visits DataTable."""

    class_section = ClassSectionSerializer(read_only=True)
    added_by_display = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(format='%m/%d/%Y', read_only=True)
    remove_url = serializers.SerializerMethodField()

    def get_added_by_display(self, obj):
        if obj.added_by is None:
            return ''
        return f"{obj.added_by.last_name}, {obj.added_by.first_name}"

    def get_remove_url(self, obj):
        try:
            return reverse(
                'class_visit:ce_not_needed_remove',
                kwargs={'pk': obj.id}
            )
        except Exception:
            return '#'

    class Meta:
        model = NotNeededVisit
        fields = [
            'id',
            'class_section',
            'added_by_display',
            'created_at',
            'remove_url',
        ]
        datatables_always_serialize = [
            'id',
            'class_section',
            'added_by_display',
            'created_at',
            'remove_url',
        ]
