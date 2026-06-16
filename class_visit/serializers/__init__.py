from rest_framework import serializers

from cis.serializers.highschool_admin import CustomUserSerializer
from cis.serializers.class_section import ClassSectionSerializer, ClassSectionSyllabiBareBoneSerializer

from cis.models.section import ClassSection, ClassSectionSyllabi

from cis.models.note import ClassVisitReportNote

from cis.serializers.course import (
    CourseSerializer, CampusSerializer,
    LocationSerializer
)
from cis.serializers.highschool import HighSchoolSerializer
from cis.serializers.teacher import TeacherSerializer, CustomUserSerializer
from cis.serializers.term import TermSerializer


from ..models import VisitSchedule, VisitReportFile

class VisitScheduleSerializer(serializers.ModelSerializer):
    class_sections = ClassSectionSerializer(many=True)
    visitors = CustomUserSerializer(many=True)
    
    visit_date = serializers.DateTimeField(
        format='%Y-%m-%d'
    )
    createdon = serializers.DateTimeField(
        format='%Y-%m-%d'
    )
    
    has_started_report = serializers.CharField(
        read_only=True
    )
    has_submitted_report = serializers.CharField(
        read_only=True
    )
    
    ce_url = serializers.CharField(
        read_only=True
    )
    
    visit_report_faculty_url = serializers.CharField(
        read_only=True
    )

    delete_url = serializers.CharField(
        read_only=True
    )

    payment_status_sexy = serializers.CharField()

    class Meta:
        model = VisitSchedule
        fields = '__all__'
        datatables_always_serialize = [
            'id',
            'class_sections',
            'visitors',
            'visit_date',
            'ce_url',
            'has_started_report',
            'has_submitted_report',
            'visit_report_faculty_url',
            'payment_status_sexy',
            'delete_url',
            'createdon'
        ]

class VisitReportNoteSerializer(serializers.ModelSerializer):
    createdby = CustomUserSerializer()
    createdon = serializers.DateTimeField(format='%m/%d/%Y %I:%M %p')

    class Meta:
        model = ClassVisitReportNote
        fields = '__all__'

class VisitReportFileSerializer(serializers.ModelSerializer):

    file_url = serializers.ReadOnlyField(source='file.url')

    class Meta:
        model = VisitReportFile
        fields = [
            'id',
            'visit_report',
            'file',
            'uploaded_at',
            'file_url',
        ]
        read_only_fields = [
            'id',
            'uploaded_at',
            'file_url',
        ]

class ClassSectionVisitSerializer(serializers.ModelSerializer):
    # from class_visit.serializers import VisitScheduleSerializer

    course = CourseSerializer()
    campus = CampusSerializer()
    highschool = HighSchoolSerializer()

    visit_schedule = VisitScheduleSerializer(many=True)
    
    syllabi = ClassSectionSyllabiBareBoneSerializer(many=True)

    location = LocationSerializer()
    term = TermSerializer()
    teacher = TeacherSerializer()

    start_date = serializers.DateField(
        format='%m/%d/%Y'
    )
    end_date = serializers.DateField(
        format='%m/%d/%Y'
    )
    ce_url = serializers.CharField(
        read_only=True
    )

    # syllabi_links = serializers.ListField()
    schedule = serializers.CharField(read_only=True)

    start_time = serializers.SerializerMethodField()
    def get_start_time(self, obj):
        if obj.start_time == 0:
            return '12:00AM'

        import time
        return time.strftime('%I:%M%p', time.strptime(str(obj.start_time), '%H%M'))

    end_time = serializers.SerializerMethodField()
    def get_end_time(self, obj):
        if obj.end_time == 0:
            return '12:00AM'

        import time
        return time.strftime('%I:%M%p', time.strptime(str(obj.end_time), '%H%M'))

    class Meta:
        model = ClassSection
        fields = '__all__'

        datatables_always_serialize = [
            'section_number',
            'class_number',
            'period_time',
            'free_period',
            'course.cohort.designator',
            'course.catalog_number',
            'course.title',
            'course',
            'location',
            'teacher',
            'credit_hours',
            'prereq',
            'days',
            'start_time',
            'end_time',
            'start_date',
            'end_date',
            'max_enrollment',
            'min_enrollment',
            'enrollment',
            'schedule',
            'ce_url',
            'grade_status',
            'visit_schedule',
            'syllabi'
            # 'syllabi_links'
        ]
