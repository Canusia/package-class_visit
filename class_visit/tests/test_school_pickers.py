"""Campus-scoped school filter on the unscheduled-classes report
(cis HighSchoolCampus). It listed every school, so scoping uses
scope_highschools (any link status), not the Active-only picker."""
from types import SimpleNamespace

import uuid

from django.conf import settings
from django.test import TestCase, override_settings

from cis.campus_context import campus_context
from cis.models.course import Campus
from cis.models.highschool import HighSchool, HighSchoolCampus


def _sfx():
    return uuid.uuid4().hex[:8]


def _campus():
    return Campus.objects.create(
        name=f"C-{_sfx()}", code=f"{settings.CAMPUS_CODE_PREFIX}_{_sfx()[:6]}")


def _hs(name, campus=None, status="Active"):
    hs = HighSchool.objects.create(name=name, code=_sfx())
    HighSchoolCampus.objects.filter(highschool=hs).delete()
    if campus is not None:
        HighSchoolCampus.objects.create(
            highschool=hs, campus=campus, status=status)
    return hs


class _Base(TestCase):
    def setUp(self):
        self.a, self.b = _campus(), _campus()
        self.mine = _hs("Mine", self.a)
        self.foreign = _hs("Foreign", self.b)
        self.dormant = _hs("Dormant", self.a, "Inactive")


from ..reports.unscheduled_classes import unscheduled_classes


class _User:
    def __init__(self, superuser=False):
        self.is_superuser = superuser

    def get_roles(self):
        return ['ce']


def _request(superuser=False):
    return SimpleNamespace(user=_User(superuser), GET={'report_id': '1'})


def _names(request=None):
    return sorted(unscheduled_classes(request).fields['highschool']
                  .queryset.values_list('name', flat=True))


@override_settings(MULTI_CAMPUS=True)
class MultiCampusTests(_Base):
    def test_excludes_other_campus_but_keeps_inactive_link(self):
        with campus_context(self.a):
            self.assertEqual(_names(_request()), ['Dormant', 'Mine'])

    def test_follows_the_request_campus(self):
        with campus_context(self.b):
            self.assertEqual(_names(_request()), ['Foreign'])

    def test_superuser_sees_every_school(self):
        with campus_context(self.a):
            names = _names(_request(superuser=True))
        self.assertIn('Foreign', names)
        self.assertIn('Mine', names)


@override_settings(MULTI_CAMPUS=False)
class SingleCampusTests(_Base):
    def test_options_are_the_campus_linked_schools(self):
        with campus_context(self.a):
            self.assertEqual(_names(_request()), ['Dormant', 'Mine'])
