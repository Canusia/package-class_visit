# class_visit/class_visit/serializers/instructor.py
from rest_framework import serializers

from cis.serializers.class_section import ClassSectionSerializer
from cis.serializers.highschool_admin import CustomUserSerializer

from ..models import VisitSchedule


class InstructorVisitScheduleSerializer(serializers.ModelSerializer):
    class_sections = ClassSectionSerializer(many=True, read_only=True)
    visitors = CustomUserSerializer(many=True, read_only=True)

    visit_date = serializers.DateTimeField(format='%m/%d/%Y', read_only=True)
    createdon = serializers.DateTimeField(format='%m/%d/%Y', read_only=True)

    has_submitted_report = serializers.BooleanField(read_only=True)

    confirmed = serializers.SerializerMethodField()
    def get_confirmed(self, obj):
        return bool(obj.meta.get('confirmed_on'))

    report_detail_url = serializers.SerializerMethodField()
    def get_report_detail_url(self, obj):
        from django.urls import reverse
        return reverse(
            'instructor_class_visit:report_detail',
            kwargs={'visit_id': obj.id}
        )

    class Meta:
        model = VisitSchedule
        fields = [
            'id',
            'visit_date',
            'createdon',
            'class_sections',
            'visitors',
            'type_of_visit',
            'has_submitted_report',
            'confirmed',
            'report_detail_url',
        ]
        datatables_always_serialize = [
            'id',
            'class_sections',
            'visitors',
            'visit_date',
            'type_of_visit',
            'has_submitted_report',
            'confirmed',
            'report_detail_url',
        ]
