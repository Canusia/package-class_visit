"""Template tags for templates that are rendered without a class_visit view."""
from django import template

from ..services.payment import payment_tracking_enabled

register = template.Library()


@register.simple_tag(takes_context=True)
def class_visit_payment_tracking(context):
    """Whether payment tracking is on, for partials included from other apps (#19).

    `schedule/class_visits.html` is included by CE detail-page tabs in `cis`,
    which pass no flag. A `payment_tracking_enabled` already in the context
    wins, so a caller (or a DB-free test) can decide; otherwise read the setting.
    """
    if 'payment_tracking_enabled' in context:
        return bool(context['payment_tracking_enabled'])
    return payment_tracking_enabled()
