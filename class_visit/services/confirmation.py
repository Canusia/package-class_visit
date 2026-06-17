"""
Confirmation token helpers for class_visit instructor confirmation flow.

The token is stored in VisitSchedule.meta['confirmation_token'] as a uuid4 hex string.
"""
import datetime

from django.contrib.sites.models import Site
from django.urls import reverse


def confirmation_url(visit_schedule) -> str:
    """
    Return the absolute HTTPS URL for the instructor to confirm the visit.

    Calls visit_schedule.ensure_confirmation_token() to guarantee the token exists.
    URL name: 'instructor_class_visit:confirm_visit' with kwarg token=<token>.

    The site domain is read from django.contrib.sites (Site.objects.get_current()).
    """
    token = visit_schedule.ensure_confirmation_token()
    site = Site.objects.get_current()
    path = reverse('instructor_class_visit:confirm_visit', kwargs={'token': token})
    return f'https://{site.domain}{path}'


def confirm_visit(token: str):
    """
    Find the VisitSchedule with the given confirmation token, mark it confirmed,
    and return the instance. Returns None if no matching schedule is found.

    Sets meta['confirmed_on'] to today's date string (m/d/Y).
    """
    from ..models import VisitSchedule

    try:
        vs = VisitSchedule.objects.get(meta__confirmation_token=token)
    except VisitSchedule.DoesNotExist:
        return None

    vs.meta['confirmed_on'] = datetime.datetime.now().strftime('%m/%d/%Y')
    vs.save(update_fields=['meta'])
    return vs
