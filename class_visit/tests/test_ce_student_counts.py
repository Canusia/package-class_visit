"""The CE visits table shows enrollment counts for each visited section.

Both numbers come from annotations on the nested section rows, using the same
definitions as the CE sections table (cis.views.section):

  num_students        every StudentRegistration on the section
  registered_students only those with status='registered'

ClassSectionSerializer declares them as read-only IntegerFields, so they are
None unless the queryset feeding the nested prefetch is annotated.
"""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from cis.models.course import Cohort, Course
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from ..models import VisitSchedule
from ..views.ce import CEVisitScheduleViewSet

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class CEVisitStudentCountsTest(TestCase):
    def setUp(self):
        self._saved_receivers = list(user_logged_in.receivers)
        user_logged_in.receivers = []

        self.staff = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x',
            is_staff=True)
        self.staff.groups.add(Group.objects.get_or_create(name='ce')[0])
        self.client.force_login(self.staff)

        # Student.save() assigns the 'student' group, which must already exist
        Group.objects.get_or_create(name='student')

        # StudentRegistration's post_save receiver writes a student note via a
        # system CustomUser that no fixture here creates. The counts under test
        # don't depend on it.
        from django.db.models.signals import post_save
        from cis.signals.registrations import update_registration
        post_save.disconnect(update_registration, sender=StudentRegistration)
        self.addCleanup(
            post_save.connect, update_registration, sender=StudentRegistration)

        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        self.term = Term.objects.create(
            academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        course = Course.objects.create(
            catalog_number='101', title='Intro', cohort=cohort)
        teacher = Teacher.objects.create(user=User.objects.create_user(
            username=f't_{_sfx()}', email=f't_{_sfx()}@x.com', password='x'))
        self.section = ClassSection.objects.create(
            class_number='1001', section_number='02', term=self.term,
            course=course, teacher=teacher, status='A')

        # 2 registered, 1 applied, 1 dropped -> 4 total, 2 registered
        for status in ('registered', 'registered', 'applied', 'dropped'):
            StudentRegistration.objects.create(
                class_section=self.section, status=status,
                # JSONField keyed by status, not a datetime column
                status_changed_on={f'{status}_on': '07/30/2026'},
                student=self._student())

        self.visit = VisitSchedule.objects.create(
            visit_date=timezone.now(), type_of_visit='Observation')
        self.visit.class_sections.add(self.section)

    def tearDown(self):
        user_logged_in.receivers = self._saved_receivers

    def _student(self):
        return Student.objects.create(user=User.objects.create_user(
            username=f's_{_sfx()}', email=f's_{_sfx()}@x.com', password='x'))

    def _nested_section(self):
        request = RequestFactory().get('/ce/class_visits/api/visit_schedule/')
        request.user = self.staff
        viewset = CEVisitScheduleViewSet()
        viewset.request = request
        from ..serializers.ce import CEVisitScheduleSerializer
        visit = viewset.get_queryset().get(pk=self.visit.id)
        return CEVisitScheduleSerializer(visit).data['class_sections'][0]

    def test_counts_are_annotated_onto_the_nested_section(self):
        section = self._nested_section()
        self.assertEqual(section['num_students'], 4)
        self.assertEqual(section['registered_students'], 2)

    def test_counts_reach_the_datatables_api(self):
        resp = self.client.get(
            '/ce/class_visits/api/visit_schedule/?format=datatables'
            '&draw=1&start=0&length=10')
        self.assertEqual(resp.status_code, 200)
        rows = [r for r in resp.json()['data'] if r['id'] == str(self.visit.id)]
        self.assertEqual(len(rows), 1)
        section = rows[0]['class_sections'][0]
        self.assertEqual(section['num_students'], 4)
        self.assertEqual(section['registered_students'], 2)

    def test_counting_does_not_duplicate_visit_rows(self):
        """Annotating via Prefetch keeps the outer visit queryset unjoined."""
        request = RequestFactory().get('/ce/class_visits/api/visit_schedule/')
        request.user = self.staff
        viewset = CEVisitScheduleViewSet()
        viewset.request = request
        ids = list(viewset.get_queryset().values_list('id', flat=True))
        self.assertEqual(ids.count(self.visit.id), 1)

    def test_table_declares_both_columns(self):
        html = self.client.get(reverse('class_visit:ce_index')).content.decode()
        self.assertIn('# Students', html)
        self.assertIn('# Registered', html)

    def test_header_and_column_counts_stay_in_step(self):
        """Column defs are positional — a header without a def shifts cells."""
        import re
        html = self.client.get(reverse('class_visit:ce_index')).content.decode()
        thead = re.search(
            r'id="tbl_visits".*?<thead>(.*?)</thead>', html, re.S).group(1)
        headers = re.findall(r'<th[^>]*>(.*?)</th>', thead, re.S)
        labels = [re.sub(r'<[^>]+>', '', h).strip() for h in headers]
        self.assertEqual(
            labels[3:6], ['Section(s)', '# Students', '# Registered'])
