"""Payment tracking (#17): the single check for the `payment_tracking` setting."""


def payment_tracking_enabled() -> bool:
    """True when the class_visit `payment_tracking` setting is Yes."""
    from ..settings.class_visit import class_visit as ClassVisitSettings
    return ClassVisitSettings.from_db().get('payment_tracking', 'No') == 'Yes'
