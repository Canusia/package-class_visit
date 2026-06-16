from django.apps import AppConfig


_REPORTS_BASE = [
    {
        'name': 'scheduled_visits',
        'title': 'Scheduled Visits Export',
        'description': 'Export all scheduled class visits with sections, visitors, and report status.',
        'categories': ['Classes'],
        'available_for': ['ce'],
    },
    {
        'name': 'visit_reports',
        'title': 'Visit Reports Export',
        'description': 'Export submitted visit reports including configured report field columns.',
        'categories': ['Classes'],
        'available_for': ['ce'],
    },
    {
        'name': 'pending_visit_reports',
        'title': 'Pending Visit Reports Export',
        'description': 'Export past visits whose report is missing or not yet submitted.',
        'categories': ['Classes'],
        'available_for': ['ce'],
    },
    {
        'name': 'unscheduled_classes',
        'title': 'Unscheduled Classes Export',
        'description': 'Export class sections with no visit scheduled and not marked as not-needed.',
        'categories': ['Classes'],
        'available_for': ['ce'],
    },
]


class ClassVisitConfig(AppConfig):
    name = 'class_visit'

    CONFIGURATORS = [
        {
            'app': 'class_visit.class_visit',
            'name': 'class_visit',
            'title': 'Class Visit Settings',
            'description': '-',
            'categories': ['3'],
        },
    ]

    REPORTS = [
        {**entry, 'app': 'class_visit'}
        for entry in _REPORTS_BASE
    ]

    def ready(self):
        import class_visit.class_visit.signals  # noqa


class DevClassVisitConfig(AppConfig):
    name = 'class_visit.class_visit'

    CONFIGURATORS = ClassVisitConfig.CONFIGURATORS

    REPORTS = [
        {**entry, 'app': 'class_visit.class_visit'}
        for entry in _REPORTS_BASE
    ]

    def ready(self):
        import class_visit.class_visit.signals  # noqa
