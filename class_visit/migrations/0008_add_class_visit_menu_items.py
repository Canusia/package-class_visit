"""Inject the Class Visits nav items into the per-role `menu` setting.

The portal menus are pulled (by ``cis.menu.draw_menu``) from the DB-backed
``cis.settings.menu`` Setting, keyed ``<role>_menu`` (each a JSON string).
This data migration makes the Class Visits links appear without manual config:

- instructor_menu: add the ``instructor_class_visit`` nav item (it was new in
  this refactor and is otherwise absent).
- ce_menu: the existing ``classes`` > ``class_visits`` sub-item points at the
  old ``class_visit:visits`` route, which was renamed to ``class_visit:ce_index``
  in the refactor — fix the url so the link resolves.
- faculty_menu: ensure the existing ``class_visits`` item url is
  ``faculty_class_visit:visits`` (already correct on this tenant; set defensively).

Idempotent: re-running makes no further changes. No-ops if the menu Setting row
doesn't exist yet (e.g. before ``register_settings`` has run on a fresh install).
Depends on cis ``__latest__`` so the ``Setting`` model is present (tenant-portable).
"""
import json

from django.db import migrations

MENU_SETTING_KEY = 'cis.settings.menu'

INSTRUCTOR_ITEM = {
    'type': 'nav-item',
    'icon': 'fas fa-fw fa-calendar-check',
    'name': 'instructor_class_visit',
    'label': 'Class Visits',
    'url': 'instructor_class_visit:index',
}


def _load(value, role):
    raw = value.get(f'{role}_menu')
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def add_menu_items(apps, schema_editor):
    Setting = apps.get_model('cis', 'Setting')
    try:
        setting = Setting.objects.get(key=MENU_SETTING_KEY)
    except Setting.DoesNotExist:
        return

    value = setting.value or {}
    changed = False

    # 1. Instructor — add the nav item if absent (insert before logout, else append).
    items = _load(value, 'instructor')
    if items is not None and not any(
            i.get('name') == 'instructor_class_visit' for i in items):
        idx = next((n for n, i in enumerate(items)
                    if i.get('name') == 'logout'), len(items))
        items.insert(idx, dict(INSTRUCTOR_ITEM))
        value['instructor_menu'] = json.dumps(items)
        changed = True

    # 2. Faculty — ensure the existing class_visits item url is current.
    items = _load(value, 'faculty')
    if items is not None:
        for i in items:
            if i.get('name') == 'class_visits' and i.get('url') != 'faculty_class_visit:visits':
                i['url'] = 'faculty_class_visit:visits'
                value['faculty_menu'] = json.dumps(items)
                changed = True
                break

    # 3. CE — fix the classes > class_visits sub-item url to the renamed route.
    items = _load(value, 'ce')
    if items is not None:
        for i in items:
            if i.get('name') == 'classes':
                for sub in i.get('sub_menu', []):
                    if sub.get('name') == 'class_visits' and sub.get('url') != 'class_visit:ce_index':
                        sub['url'] = 'class_visit:ce_index'
                        value['ce_menu'] = json.dumps(items)
                        changed = True
                break

    if changed:
        setting.value = value
        setting.save()


def remove_menu_items(apps, schema_editor):
    """Reverse: drop the instructor nav item. The faculty/ce url fixes are left
    in place — their prior values aren't recoverable and the new urls are valid."""
    Setting = apps.get_model('cis', 'Setting')
    try:
        setting = Setting.objects.get(key=MENU_SETTING_KEY)
    except Setting.DoesNotExist:
        return

    value = setting.value or {}
    items = _load(value, 'instructor')
    if items is not None:
        pruned = [i for i in items if i.get('name') != 'instructor_class_visit']
        if len(pruned) != len(items):
            value['instructor_menu'] = json.dumps(pruned)
            setting.value = value
            setting.save()


class Migration(migrations.Migration):

    dependencies = [
        ('class_visit', '0007_migrate_class_visit_emails_settings'),
        ('cis', '__first__'),
    ]

    operations = [
        migrations.RunPython(add_menu_items, remove_menu_items),
    ]
