"""Class visit sidebar items (cis.menu_registry).

Ids are the legacy names. ce `class_visits` is the 30 of `classes`; faculty
`class_visits` is the 30 of the faculty menu; instructor
`instructor_class_visit` (migration 0008) sits before `logout` (90).
On a cis without the registry nothing registers.
"""
try:
    from cis.menu_registry import menu
except ImportError:   # cis without the registry: the menu migrations still apply
    menu = None

if menu is not None:
    menu.register('ce', 'class_visits', 'Class Visits/Reports',
                  url='class_visit:ce_index', parent='classes', order=30)
    menu.register('faculty', 'class_visits', 'Class Observations',
                  url='faculty_class_visit:visits', icon='fas fa-fw fa-route', order=30)
    menu.register('instructor', 'instructor_class_visit', 'Class Visits',
                  url='instructor_class_visit:index',
                  icon='fas fa-fw fa-calendar-check', order=85)
