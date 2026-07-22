# myce_class_visit

Class-visit management for **MyCE** (My Concurrent Enrollment). A pip-installable Django app, shipped as a git submodule across MyCE tenants (same pattern as `pd_event` / `future_sections`).

It lets:

- **Faculty** schedule classroom visits (for sections they oversee, filtered by status and excluding a "not needed" list; all sections on one visit must share the same instructor), write a configurable visit report, and bulk-export visit letters as PDF.
- **Instructors** view their scheduled visits, confirm a visit via an emailed link, and see the **public** report fields after a report is submitted (public-only PDF export).
- **CE staff** do full CRUD on visits, manage the "not needed visit" list, see the **entire** report, run reports, and send reminders.

## Contents / URLs

| Role | URL prefix | Namespace | Landing route |
|------|------------|-----------|---------------|
| CE staff | `/ce/class_visits/` | `class_visit` | `class_visit:ce_index` |
| Faculty | `/faculty/class_visits/` | `faculty_class_visit` | `faculty_class_visit:visits` |
| Instructor | `/instructor/class_visits/` | `instructor_class_visit` | `instructor_class_visit:index` |

Each role has its own DRF router under `…/api/` (DataTables server-side). Models: `VisitSchedule`, `VisitReport` (one per schedule), `VisitReportFile`, `NotNeededVisit`.

## Requirements

A MyCE tenant providing the host `cis` app plus: `setting`, `report`, `django-mailer`, `djangorestframework`, `rest_framework_datatables`, and `pdfkit` (with the `wkhtmltopdf` binary, for PDF letters). Python ≥ 3.8, Django ≥ 3.2.

---

## Installation

The app uses the **dual-config / `find_spec`** pattern: when the inner package `class_visit.class_visit` is importable (submodule checked out for dev), `DevClassVisitConfig` is used; otherwise the pip-installed `ClassVisitConfig`.

### 1. Add the package

**Production — pip pin** in `webapp/requirements.txt`:

```
git+https://github.com/Canusia/package-class_visit@v0.0.1
```

**Development — editable git submodule:**

```bash
git submodule add https://github.com/Canusia/package-class_visit.git webapp/class_visit
cd webapp/class_visit && git checkout v0.0.1 && cd -
git add .gitmodules webapp/class_visit && git commit -m "Add class_visit submodule @ v0.0.1"
```

(After cloning a tenant that already uses the submodule: `git submodule update --init webapp/class_visit`.)

### 2. `INSTALLED_APPS` (`myce/settings.py`)

```python
import importlib.util

INSTALLED_APPS += [
    'class_visit.class_visit.apps.DevClassVisitConfig'
    if importlib.util.find_spec('class_visit.class_visit')
    else 'class_visit.apps.ClassVisitConfig',
]
```

### 3. `STATICFILES_DIRS` (`myce/settings.py`)

Uses the tenant's existing `get_package_path()` helper:

```python
STATICFILES_DIRS += [
    os.path.join(get_package_path("class_visit.class_visit"), 'staticfiles')
    if importlib.util.find_spec('class_visit.class_visit')
    else os.path.join(get_package_path("class_visit"), 'staticfiles'),
]
```

### 4. URLs (`myce/urls.py`)

```python
import importlib.util
_cv = 'class_visit.class_visit' if importlib.util.find_spec('class_visit.class_visit') else 'class_visit'

urlpatterns += [
    path('ce/class_visits/',         include(f'{_cv}.urls.ce')),
    path('faculty/class_visits/',    include(f'{_cv}.urls.faculty')),
    path('instructor/class_visits/', include(f'{_cv}.urls.instructor')),
]
```

### 5. Migrate

```bash
python manage.py migrate class_visit
```

Creates `VisitSchedule`, `VisitReport`, `VisitReportFile`, `NotNeededVisit`. Cross-app dependencies are pinned to `('cis', '__first__')`, so the migrations are tenant-portable. Migration `0007` copies any legacy email-template values from the old host setting into this app's setting (see cleanup below); `0008` injects the menu items (see step 7).

### 6. Register settings & reports

```bash
python manage.py register_settings   # adds the "Class Visit Settings" configurator
python manage.py register_reports     # adds the 4 reports below
```

Reports (CE → Reports): **Scheduled Visits**, **Visit Reports**, **Pending Visit Reports** (visit past, report not submitted), **Unscheduled Classes**.

### 7. Menu entries

Portal menus are rendered by `cis.menu.draw_menu`, which pulls items from the per-role `menu` setting (`<role>_menu`, JSON). Migration **`0008_add_class_visit_menu_items`** adds them automatically on **existing** tenants (adds the instructor item; fixes the CE sub-item URL). On a **fresh** tenant where the menu setting is seeded from `register_settings` defaults, add them in **Settings → Menu**:

- **instructor_menu** (top-level nav item):
  ```json
  {"type":"nav-item","icon":"fas fa-fw fa-calendar-check","name":"instructor_class_visit","label":"Class Visits","url":"instructor_class_visit:index"}
  ```
- **faculty_menu** (top-level nav item): `name` `class_visits`, `url` `faculty_class_visit:visits`.
- **ce_menu** → under the `classes` nav item's `sub_menu`: `name` `class_visits`, `url` `class_visit:ce_index`.

### 8. Reminder cron

`send_visit_report_reminders` emails visitors whose report is overdue (cadence = the `reminder_every_days` setting). Register it with the tenant's CronTab:

```bash
python manage.py shell -c "from cis.models.crontab import CronTab; CronTab.objects.get_or_create(command='send_visit_report_reminders', defaults={'cron': '0 7 * * *'})"
```

The tenant's `cron_jobs` dispatcher then calls it on schedule. Run once manually to verify: `python manage.py send_visit_report_reminders`.

### 9. Collect static & restart

```bash
python manage.py collectstatic --noinput
```

---

## Configuration

**Settings → Classes → Class Visit Settings** (setting key `class_visit`):

- `is_active` (Yes / No / Debug) + `debug_email_list`
- `report_fields_json` — JSON array defining the report fields: `{"name","label","type"(text|textarea|select|checkbox|date),"public"(bool),"required"(bool),"options"[…],"visit_types"[…]}`. Values are stored in `VisitReport.meta`; `public` controls instructor visibility and public-only PDFs. **Validated on save** — malformed JSON, bad `type`, duplicate `name`, `select` without `options`, or a `visit_types` value not in the configured Visit Types is rejected (rather than silently blanking the fields). Optional **`visit_types`** limits a field to those visit types (omit/empty = all types).
- `visit_types` — pipe-delimited (e.g. `Initial|Follow-up|Annual`). Rendered before Report Fields in the settings form.
- `section_status_filter` — `active` (status `A`) / `inactive` (`C`) / `all`; drives the schedulable-section lists
- `notify_target` (course administrator / generic email) + `generic_email`
- `notify_teacher_on_schedule` + `teacher_scheduled_subject` / `teacher_scheduled_message`
- `instructor_confirm_link` — when Yes, the `{{confirmation_link}}` shortcode is populated in the scheduled email
- `notify_teacher_on_submit` + `teacher_submit_subject` / `teacher_submit_message`
- `visitor_reminder_subject` / `visitor_reminder_message` + `reminder_every_days`
- `payment_tracking` (Yes / No) — when Yes, CE staff can **Mark Selected as Paid** on the CE visits page, and both the CE and faculty visits tables show a **Payment Status** column. (Shown at the bottom of the settings form.)
- `notify_visitor_on_paid` (Yes / No) + `visitor_paid_subject` / `visitor_paid_message` — when payment tracking is on and this is Yes, each visitor is emailed when their report is marked paid. The message uses the same shortcodes as the visitor reminder: `{{visitor_first_name}}`, `{{visit_date}}`, `{{class_sections}}`, `{{report_url}}`.

The CE **View Report** button opens the report in an in-page iframe modal.

---

## Post-install: removing the deprecated `class_visit_emails` from the host `cis` app

Older MyCE tenants kept the class-visit email templates in the **host** module `cis/settings/class_visit_emails.py` (stored under `Setting` key `cis.settings.class_visit_emails`). This package replaces it with its own in-app settings class (key `class_visit`), and migration `0007_migrate_class_visit_emails_settings` copies the old values into the new key on deploy. After you've confirmed the new settings exist, remove the dead host-side pieces **in the tenant repo (e.g. `ewu`), not in this package**:

1. **Confirm migration 0007 ran** and the new setting is populated:
   ```bash
   python manage.py shell -c "from cis.models.settings import Setting; print('new:', Setting.objects.filter(key='class_visit').exists())"
   ```
2. **Delete the deprecated settings module:**
   ```bash
   git rm webapp/cis/settings/class_visit_emails.py
   ```
3. **Confirm the old configurator is gone from `cis/apps.py`** — `CisConfig.CONFIGURATORS` must no longer contain the `{'name': 'class_visit_emails', …}` entry. (The class_visit refactor already removes it; verify after merge.)
   ```bash
   grep -n "class_visit_emails" webapp/cis/apps.py   # expect: no output
   ```
4. **Remove the stale registry row** so the Settings UI doesn't try to import the deleted module:
   ```bash
   python manage.py shell -c "
   try:
       from setting.setting.models.setting import SettingRecord
   except ImportError:
       from setting.models.setting import SettingRecord
   SettingRecord.objects.filter(name='class_visit_emails').delete()
   "
   ```
5. **(Optional) Drop the migrated-from value row** — only after confirming step 1:
   ```bash
   python manage.py shell -c "from cis.models.settings import Setting; Setting.objects.filter(key='cis.settings.class_visit_emails').delete()"
   ```
6. **No action needed** for `cis/models/section.py` (the refactor changed its top-level `from class_visit.models import VisitSchedule` to a lazy import) or for `cis/models/note.py`'s `ClassVisitReportNote` (it keeps its FK to `class_visit.VisitReport`).

Then run the suite and `python manage.py check` to confirm nothing references the removed module.

---

## Versioning

Tag-driven; pin a tag in `requirements.txt` (e.g. `@v0.0.1`) and point the submodule at the same tag. Bump the tag for releases.
