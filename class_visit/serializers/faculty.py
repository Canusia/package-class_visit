"""DRF serializers for the Faculty class-visit portal."""
from rest_framework import serializers
from django.urls import reverse

from cis.models.section import ClassSection
from cis.serializers.class_section import ClassSectionSyllabiBareBoneSerializer
from cis.serializers.course import CourseSerializer, CampusSerializer, LocationSerializer
from cis.serializers.highschool import HighSchoolSerializer
from cis.serializers.teacher import TeacherSerializer, CustomUserSerializer
from cis.serializers.term import TermSerializer

from class_visit.class_visit.models import VisitSchedule


class _MinimalVisitScheduleSerializer(serializers.ModelSerializer):
    """Minimal nested VisitSchedule for embedding inside a ClassSection row."""
    visit_date = serializers.DateTimeField(format='%m/%d/%Y', allow_null=True)
    manage_visit_url = serializers.SerializerMethodField()

    def get_manage_visit_url(self, obj):
        try:
            first_section = obj.class_sections.all()[0]
            return reverse(
                'faculty_class_visit:edit_visit',
                kwargs={'class_section_id': first_section.id, 'visit_id': obj.id},
            )
        except (IndexError, Exception):
            return ''

    class Meta:
        model = VisitSchedule
        fields = ['id', 'visit_date', 'manage_visit_url']
        datatables_always_serialize = ['id', 'visit_date', 'manage_visit_url']


class FacultySchedulableSectionSerializer(serializers.ModelSerializer):
    """Serializer for the 'Add Observation Date(s)' DataTable.

    Lists ClassSections the faculty user can schedule visits for.
    The visit_schedule field nests all existing visits for each section.
    """
    course = CourseSerializer()
    campus = CampusSerializer()
    highschool = HighSchoolSerializer()
    syllabi = ClassSectionSyllabiBareBoneSerializer(many=True)
    location = LocationSerializer()
    term = TermSerializer()
    teacher = TeacherSerializer()
    visit_schedule = _MinimalVisitScheduleSerializer(many=True)

    start_date = serializers.DateField(format='%m/%d/%Y', allow_null=True)
    end_date = serializers.DateField(format='%m/%d/%Y', allow_null=True)

    schedule_visit_url = serializers.SerializerMethodField()

    def get_schedule_visit_url(self, obj):
        return reverse(
            'faculty_class_visit:manage_visit',
            kwargs={'class_section_id': obj.id},
        )

    class Meta:
        model = ClassSection
        fields = '__all__'
        datatables_always_serialize = [
            'id',
            'section_number',
            'class_number',
            'period_time',
            'course',
            'highschool',
            'location',
            'teacher',
            'term',
            'syllabi',
            'visit_schedule',
            'schedule_visit_url',
        ]


class FacultyVisitScheduleSerializer(serializers.ModelSerializer):
    """Serializer for the 'Scheduled Observations' DataTable.

    Includes action URLs for managing the visit and its report.
    """
    class_sections = serializers.SerializerMethodField()

    def get_class_sections(self, obj):
        from cis.serializers.class_section import ClassSectionSerializer
        return ClassSectionSerializer(obj.class_sections.all(), many=True).data

    visitors = CustomUserSerializer(many=True)

    visit_date = serializers.DateTimeField(format='%m/%d/%Y', allow_null=True)
    createdon = serializers.DateTimeField(format='%m/%d/%Y')

    has_started_report = serializers.SerializerMethodField()

    def get_has_started_report(self, obj):
        return str(obj.has_started_report)

    has_submitted_report = serializers.SerializerMethodField()

    def get_has_submitted_report(self, obj):
        return str(obj.has_submitted_report)

    manage_visit_url = serializers.SerializerMethodField()

    def get_manage_visit_url(self, obj):
        try:
            first_section = obj.class_sections.all()[0]
            return reverse(
                'faculty_class_visit:edit_visit',
                kwargs={'class_section_id': first_section.id, 'visit_id': obj.id},
            )
        except (IndexError, Exception):
            return ''

    edit_report_url = serializers.SerializerMethodField()

    def get_edit_report_url(self, obj):
        return reverse(
            'faculty_class_visit:edit_visit_report',
            kwargs={'visit_id': obj.id},
        )

    delete_url = serializers.SerializerMethodField()

    def get_delete_url(self, obj):
        return reverse(
            'faculty_class_visit:delete_visit',
            kwargs={'visit_id': obj.id},
        )

    class Meta:
        model = VisitSchedule
        fields = '__all__'
        datatables_always_serialize = [
            'id',
            'visit_date',
            'createdon',
            'class_sections',
            'visitors',
            'has_started_report',
            'has_submitted_report',
            'manage_visit_url',
            'edit_report_url',
            'delete_url',
        ]
