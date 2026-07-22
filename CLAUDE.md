# CLAUDE.md — `class_visit` package

Guidance for Claude Code when working **inside this submodule**. This is the pip-installable
`myce_class_visit` Django app (repo `Canusia/package-class_visit`), vendored as a git
submodule into MyCE tenants at `webapp/class_visit/`. The host tenant for this checkout is
**ewu**.

For install/config/menu/cron wiring see [`README.md`](README.md). For the client-facing
configuration questionnaire and the pre-sales capabilities sheet, see
[`docs/`](docs/).

## What this app does

Manages **classroom observation visits** to concurrent-enrollment sections and the structured
**visit report** each one produces. CE staff and faculty schedule visits; visitors write
reports; instructors confirm visits and view the public portion of reports. Emails fire at
schedule time, on report submit, and as overdue-report reminders.

## Layout

This is the **dual-package** pattern: an outer proxy package and the real inner package.

```
class_visit/                 ← outer package (submodule root, this dir)
  __init__.py                ← MUST stay import-free (outer root)
  models.py                  ← thin proxy re-export for legacy import paths
  setup.cfg / pyproject.toml ← packaging (name: myce_class_visit)
  MANIFEST.in                ← ships non-.py data dirs (templates, staticfiles, …)
  README.md / docs/          ← install guide + client workbook & capabilities sheet
  class_visit/               ← the REAL app package (import root)
    apps.py                  ← ClassVisitConfig (installed) / DevClassVisitConfig (submodule)
    models.py                ← VisitSchedule, VisitReport, VisitReportFile, NotNeededVisit
    forms/{ce,faculty}.py
    views/{ce,faculty,instructor}.py
    serializers/{ce,faculty,instructor}.py
    urls/{ce,faculty,instructor}.py
    settings/class_visit.py  ← the single Setting (key 'class_visit')
    services/{emails,report_fields,confirmation,pdf}.py
    signals.py
    reports/                 ← report definitions registered via apps.REPORTS
    management/commands/send_visit_report_reminders.py
    templates/class_visit/{ce,faculty,instructor}/
    staticfiles/class_visit/
    tests/
    migrations/
```

### The dual-config / `find_spec` rule

The host decides which `AppConfig` to load based on whether the inner package is importable:

- Submodule checked out (this repo present) → `class_visit.class_visit.apps.DevClassVisitConfig`
  (`name = 'class_visit.class_visit'`).
- Pip-installed only → `class_visit.apps.ClassVisitConfig` (`name = 'class_visit'`).

Because the import root differs between the two modes, **never hardcode `class_visit.` or
`class_visit.class_visit.` import prefixes** in app code. Use relative imports within the
package, and where an absolute reference is unavoidable resolve it the way the host does
(`importlib.util.find_spec('class_visit.class_visit')`). The outer `__init__.py` stays empty
on purpose — adding imports there breaks the pip-installed mode.

## Running commands

This code runs inside the host tenant's container, not here. Use the ewu container, pointed at
the live mount:

```bash
docker exec -w /app/webapp django_web_ewu python manage.py test class_visit          # app tests
docker exec -w /app/webapp django_web_ewu python manage.py makemigrations class_visit
docker exec -w /app/webapp django_web_ewu python manage.py migrate class_visit
docker exec -w /app/webapp django_web_ewu python manage.py send_visit_report_reminders
```

The app label is `class_visit` in both modes (set by `apps.py`), so `manage.py … class_visit`
is correct regardless of which config is active.

## Models (quick reference)

| Model | Notes |
|-------|-------|
| `VisitSchedule` | A scheduled visit. M2M `visitors` (CustomUser) + `class_sections` (all must share one teacher). `type_of_visit` from the `visit_types` setting. State lives in `meta` (pre_visit_note, confirmation_token, reminder_last_sent_on, …). |
| `VisitReport` | One-to-one with a schedule (`related_name='report'`). `status` Draft→Submitted; submit fires notifications. Dynamic report fields stored in `meta`, defined by `report_fields_json`. `payment_processed` flag (only when Submitted). |
| `VisitReportFile` | Attachments on a report (PrivateMediaStorage). |
| `NotNeededVisit` | Flags a `ClassSection` as exempt so it drops off the unscheduled list. |

## Configuration surface

One `Setting` row, key `class_visit`, defined in `settings/class_visit.py`. The client-facing
explanation of every option is in [`docs/class-visit-configuration-workbook.md`](docs/class-visit-configuration-workbook.md);
keep that workbook in sync when you add, rename, or remove a setting. Keys:
`is_active` / `debug_email_list`, `report_fields_json`, `visit_types`, `section_status_filter`,
`notify_target` / `generic_email`, `notify_teacher_on_schedule` + subject/message,
`instructor_confirm_link`, `notify_teacher_on_submit` + subject/message,
`visitor_reminder_subject` / `visitor_reminder_message`, `reminder_every_days`,
`payment_tracking`, `notify_visitor_on_paid` / `visitor_paid_subject` / `visitor_paid_message`.

Notes on recent additions:
- **`report_fields_json` is validated on save** (`settings/class_visit.py::clean_report_fields_json`) —
  malformed JSON, bad `type`, duplicate `name`, `select` without `options`, and `visit_types`
  values not in the configured Visit Types are rejected instead of silently storing empty config.
- Each report-field def may carry **`"visit_types": [...]`** to show only for those visit types
  (empty/absent = all); filtering lives in `services/report_fields.py` (`get_report_field_defs(type_of_visit=…)`).
- **Payment tracking** (`payment_tracking`): when Yes, the CE visits page (`views/ce.py::do_bulk_action`,
  action `mark_as_paid`) can mark submitted reports paid via `VisitReport.mark_as_payment_processed()`,
  and both the CE and faculty visits tables show a Payment Status column. Marking paid emails each
  visitor when `notify_visitor_on_paid` = Yes (`services/emails.py::notify_visitor_payment_processed`,
  same shortcodes as the visitor reminder). The payment fields render at the bottom of the settings
  form and toggle their visibility via JS injected through the crispy layout.
- The CE **View Report** opens the report in the visits-page iframe modal (`?ajax=1` → `cis/ajax-base.html`,
  `@xframe_options_exempt`).

All outbound mail routes through `services/emails.py::send_app_email`, which honors
`is_active` (Yes / No / Debug). Email bodies are settings strings rendered with Django template
shortcodes — when you add a shortcode, document it in both the setting `help_text` and the
workbook.

## When you change things here

This package ships to **many tenants**, so guard portability:

- **Migrations** — after `makemigrations`, rewrite any tenant-specific cross-app dependency
  (e.g. `('cis', '0055_…')`) to `('cis', '__first__')`. The `submod-migration-deps` skill does
  this; migrations here are already pinned that way.
- **New files / dirs** — `packages = find:` ships Python subpackages automatically, but
  **non-`.py` data** (templates, staticfiles, fixtures) only ships if covered by `MANIFEST.in`.
  Add a `recursive-include` line for any new data directory. The `submod-package-manifest`
  skill audits this; run it before tagging.
- **Versioning** — tag-driven. Bump the tag, update the host's
  `webapp/requirements.txt` pin (`@vX.Y.Z`) and the submodule pointer together. `setup.cfg` /
  `pyproject.toml` `version` stays nominal.
- **Tests** — add/adjust tests under `class_visit/tests/` and run them in the ewu container
  before committing.

## Docs in this package

| File | Audience | Purpose |
|------|----------|---------|
| `README.md` | Implementers | Install, settings wiring, menu, cron, host-cleanup steps |
| `docs/class-visit-configuration-workbook.md` | Clients | Questionnaire that gathers the values needed to configure the module |
| `docs/class-visit-native-capabilities.md` | Pre-sales / scoping | One-pager of native, configurable capabilities |
