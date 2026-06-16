from django.conf import settings  # noqa: F401 (kept for legacy compat)

from django.db.models.signals import pre_save
from django.dispatch import receiver

from class_visit.models import VisitReport


@receiver(pre_save, sender=VisitReport)
def status_changed(sender, instance, **kwargs):
    """
    visit_letter field changed — reset visit_letter_sent_on so the letter
    is re-sent on the next submission.  Non-email bookkeeping only.
    """
    from datetime import datetime  # noqa: F401

    previous_status = instance.tracker.previous('visit_letter')
    status = instance.visit_letter

    if previous_status != status:
        instance.meta['visit_letter_sent_on'] = None
