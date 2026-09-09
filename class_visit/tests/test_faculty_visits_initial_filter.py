"""The faculty Class Observations page must send its filter state on the FIRST
DataTables request.

Both tables used to be built with a bare api url string, while the term
<select> is server-rendered with the active term already selected. First paint
therefore showed the active term in the dropdown and every term's rows in the
table. Only touching the dropdown fired `change` and applied the filter — and
re-picking the term that was already selected fires no `change` at all, so the
only way out was to select a different term and come back.

The fix reads both filter forms inside `ajax.data` (the shape ce_visits.js
already uses), so the filter is applied on every request including the first.
"""
import re
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

User = get_user_model()

FILTER_FORMS = ('#class_section_filter', '#visit_filter')


def _sfx():
    return uuid.uuid4().hex[:8]


class FacultyVisitsInitialFilterTest(TestCase):
    """Guards the request shape of the two tables on faculty/visits.html."""

    def setUp(self):
        # django_login_history's post_login receiver crashes on the test
        # client's missing REMOTE_ADDR — same dance as test_views_faculty.py.
        self._receivers = list(user_logged_in.receivers)
        user_logged_in.receivers = []

        ce = Group.objects.get_or_create(name='ce')[0]  # passes the faculty guard
        self.user = User.objects.create(
            username=f'facfil_{_sfx()}@x.com',
            email=f'facfil_{_sfx()}@x.com', is_active=True)
        self.user.set_password('pw')
        self.user.save()
        self.user.groups.add(ce)
        self.client.force_login(self.user)

    def tearDown(self):
        user_logged_in.receivers = self._receivers

    def _html(self):
        resp = self.client.get(reverse('faculty_class_visit:visits'))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def test_filter_helper_is_defined(self):
        self.assertIn('function cvApplyFilter(', self._html())

    def test_both_tables_read_their_filter_form_on_every_request(self):
        html = self._html()
        for form in FILTER_FORMS:
            self.assertIn(
                "cvApplyFilter(d, '%s')" % form, html,
                'the table filtered by %s must read it inside ajax.data, so '
                'the first request carries the term the dropdown shows' % form)

    def test_no_datatable_uses_a_bare_ajax_url(self):
        """The exact bug shape: a url string instead of the object form.

        A url fixed at construction is not re-read, so the initial request
        omits the pre-selected term entirely.
        """
        bare = re.findall(r'ajax:\s*(?!\{)\S+', self._html())
        self.assertEqual(
            bare, [],
            'every DataTable on this page must use the object form '
            "`ajax: { url: ..., data: function (d) { ... } }`; a bare url "
            'string is the regression this test guards: %r' % (bare,))

    def test_change_handlers_reload_rather_than_rewriting_the_url(self):
        """Rewriting the url on change is what left the first request bare."""
        html = self._html()
        self.assertNotIn('.ajax.url(', html)
        for table in ('tbl_class_sections', 'tbl_visits'):
            self.assertIn('%s.ajax.reload();' % table, html)
