"""Payment tracking (#17): who/when audit, un-mark, export columns, report pages."""
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import Client, TestCase
from django.urls import reverse

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.course import Cohort, Course
from cis.models.section import ClassSection
from cis.models.settings import Setting
from cis.models.teacher import Teacher
from cis.models.term import AcademicYear, Term

from ..models import VisitReport, VisitSchedule
from ..services.payment import payment_tracking_enabled
from . import PKG

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


def _tracking(value):
    Setting.objects.update_or_create(
        key='class_visit', defaults={'value': {'payment_tracking': value}})


class _Fixture(TestCase):
    @classmethod
    def setUpClass(cls):
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    @classmethod
    def setUpTestData(cls):
        ay = AcademicYear.objects.create(name=f'AY-{_sfx()}')
        cls.term = Term.objects.create(academic_year=ay, code='FA', label=f'Fall-{_sfx()}')
        cohort = Cohort.objects.create(name=f'Co-{_sfx()}', designator='CO')
        course = Course.objects.create(catalog_number='101', title='A', cohort=cohort)
        teacher = Teacher.objects.create(user=User.objects.create_user(
            username=f't_{_sfx()}', email=f't_{_sfx()}@x.com', password='x'))
        section = ClassSection.objects.create(
            course=course, term=cls.term, teacher=teacher,
            class_number=f'C-{_sfx()}', section_number='001')

        cls.visitor = User.objects.create_user(
            username=f'fac_{_sfx()}', email=f'fac_{_sfx()}@x.com', password='x',
            first_name='Vic', last_name='Visitor')
        cls.visitor.groups.add(Group.objects.get_or_create(name='faculty')[0])

        cls.ce_user = User.objects.create_user(
            username=f'ce_{_sfx()}', email=f'ce_{_sfx()}@x.com', password='x',
            first_name='Pat', last_name='Payer')
        cls.ce_user.groups.add(Group.objects.get_or_create(name='ce')[0])

        cls.visit = VisitSchedule.objects.create(
            visit_date='2026-03-01', type_of_visit='Initial', meta={})
        cls.visit.class_sections.add(section)
        cls.visit.visitors.add(cls.visitor)

    def setUp(self):
        self.client = Client(REMOTE_ADDR='127.0.0.1')
        self.report = VisitReport.objects.create(
            visit_schedule=self.visit, teacher_discussion='', student_discussion='',
            visit_letter='', status='Submitted', payment_processed='')


class PaymentModelTest(_Fixture):
    def test_mark_records_who_and_history(self):
        self.report.mark_as_payment_processed(self.ce_user)
        self.report.refresh_from_db()
        self.assertEqual(self.report.payment_processed, '1')
        self.assertEqual(self.report.payment_processed_by, 'Pat Payer')
        history = self.report.meta['payment_history']
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['action'], 'paid')
        self.assertEqual(history[0]['by_id'], self.ce_user.pk)
        self.assertTrue(self.report.payment_status_sexy.endswith(' by Pat Payer'))

    def test_legacy_paid_row_has_no_dangling_by(self):
        self.report.payment_processed = '1'
        self.report.meta = {'payment_processed': '01/02/2026'}
        self.report.save()
        self.assertEqual(self.report.payment_status_sexy, 'Processed on 01/02/2026')

    def test_unmark_resets_and_appends_history(self):
        self.report.mark_as_payment_processed(self.ce_user)
        self.assertTrue(self.report.unmark_payment_processed(self.ce_user))
        self.report.refresh_from_db()
        self.assertEqual(self.report.payment_processed, '2')
        self.assertNotIn('payment_processed', self.report.meta)
        self.assertNotIn('payment_processed_by', self.report.meta)
        self.assertEqual(
            [h['action'] for h in self.report.meta['payment_history']], ['paid', 'unpaid'])
        self.assertEqual(self.report.payment_status_sexy, 'Pending')

    def test_unmark_unpaid_is_a_noop(self):
        self.assertFalse(self.report.unmark_payment_processed(self.ce_user))
        self.report.refresh_from_db()
        self.assertNotIn('payment_history', self.report.meta)

    def test_remark_after_unmark(self):
        self.report.mark_as_payment_processed(self.ce_user)
        self.report.unmark_payment_processed(self.ce_user)
        self.report.mark_as_payment_processed(self.ce_user)
        self.report.refresh_from_db()
        self.assertEqual(self.report.payment_processed, '1')
        self.assertEqual(len(self.report.meta['payment_history']), 3)

    def test_payment_tracking_enabled_reads_setting(self):
        _tracking('Yes')
        self.assertTrue(payment_tracking_enabled())
        _tracking('No')
        self.assertFalse(payment_tracking_enabled())


class CEBulkPaymentTest(_Fixture):
    def _post(self, action):
        self.client.force_login(self.ce_user)
        return self.client.post(reverse('class_visit:ce_bulk_action'),
                                {'action': action, 'ids[]': [str(self.visit.id)]})

    def test_unmark_refused_when_tracking_off(self):
        _tracking('No')
        self.assertEqual(self._post('mark_as_unpaid').status_code, 403)

    @patch(f'{PKG}.views.ce.email_service')
    def test_unmark_paid_report_sends_no_email(self, mock_emails):
        _tracking('Yes')
        self.report.mark_as_payment_processed(self.ce_user)
        resp = self._post('mark_as_unpaid')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Unmarked 1 of 1', resp.json()['message'])
        self.report.refresh_from_db()
        self.assertEqual(self.report.payment_processed, '2')
        mock_emails.notify_visitor_payment_processed.assert_not_called()

    @patch(f'{PKG}.views.ce.email_service')
    def test_mark_records_requesting_user(self, mock_emails):
        _tracking('Yes')
        self._post('mark_as_paid')
        self.report.refresh_from_db()
        self.assertEqual(self.report.meta['payment_history'][0]['by_id'], self.ce_user.pk)

    @patch(f'{PKG}.views.ce.active_term', return_value=None)
    def test_unpaid_button_follows_setting(self, _at):
        self.client.force_login(self.ce_user)
        _tracking('Yes')
        html = self.client.get(reverse('class_visit:ce_index')).content.decode()
        self.assertIn('Mark Selected as Unpaid', html)
        _tracking('No')
        html = self.client.get(reverse('class_visit:ce_index')).content.decode()
        self.assertNotIn('Mark Selected as Unpaid', html)


class VisitReportsExportPaymentTest(_Fixture):
    def _export(self):
        from ..reports.visit_reports import visit_reports
        form = visit_reports()
        report = VisitReport.objects.get(pk=self.report.pk)
        return form._headers(), form._row(report)

    def test_payment_columns_when_tracking_on(self):
        _tracking('Yes')
        self.report.mark_as_payment_processed(self.ce_user)
        headers, row = self._export()
        i = headers.index('Payment Status')
        self.assertEqual(headers[i:i + 3], ['Payment Status', 'Paid On', 'Paid By'])
        self.assertEqual(len(headers), len(row))
        self.assertTrue(row[i].startswith('Processed on'))
        self.assertEqual(row[i + 2], 'Pat Payer')

    def test_no_payment_columns_when_tracking_off(self):
        _tracking('No')
        headers, row = self._export()
        self.assertNotIn('Payment Status', headers)
        self.assertEqual(len(headers), len(row))


class ReportPagePaymentTest(_Fixture):
    def _ce_html(self):
        self.client.force_login(self.ce_user)
        return self.client.get(reverse(
            'class_visit:ce_view_report', kwargs={'visit_id': self.visit.id})).content.decode()

    def _faculty_html(self):
        self.client.force_login(self.visitor)
        return self.client.get(reverse(
            'faculty_class_visit:edit_visit_report',
            kwargs={'visit_id': self.visit.id})).content.decode()

    def test_payment_shown_when_on(self):
        _tracking('Yes')
        self.report.mark_as_payment_processed(self.ce_user)
        for html in (self._ce_html(), self._faculty_html()):
            self.assertIn('id="cv-payment-status"', html)
            self.assertIn('by Pat Payer', html)

    def test_payment_hidden_when_off(self):
        _tracking('No')
        for html in (self._ce_html(), self._faculty_html()):
            self.assertNotIn('id="cv-payment-status"', html)
