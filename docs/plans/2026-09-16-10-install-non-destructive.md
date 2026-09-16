# #10 — install() must not overwrite a configured tenant

## Problem (verified)

`class_visit/settings/class_visit.py:394-401`:

```python
try:
    setting = Setting.objects.get(key=self.key)
except Setting.DoesNotExist:
    setting = Setting()
    setting.key = self.key

setting.value = defaults      # unconditional, even on the existing row
setting.save()
```

The `try/except` only reuses the instance; the next line replaces the whole value.
`register_settings` (package-setting, `management/commands/register_settings.py:32-52`)
calls `install()` whenever no `SettingRecord` named `class_visit` exists — a state a
container can reach with the `Setting` row still populated. Result: the tenant's entire
Class Visit configuration (report fields, all email copy, visit types) is replaced by
defaults, silently, exit code 0.

Hit for real on ewu.

## Fix

Make `install()` seed-only:

1. Load the existing row's `value` (default `{}` when absent).
2. Add only keys that are **missing**. Never touch a key that is present, including one
   deliberately set to `''` or `'No'`.
3. Save only when something was added, so an ordinary boot is a no-op write.

Keep the defaults dict as-is; it is the source for new keys added by later plans (#5, #14).

```python
def install(self):
    defaults = {...}                      # unchanged
    setting, _ = Setting.objects.get_or_create(
        key=self.key, defaults={'value': {}})
    value = setting.value if isinstance(setting.value, dict) else {}
    added = {k: v for k, v in defaults.items() if k not in value}
    if added:
        setting.value = {**value, **added}
        setting.save()
```

`run_record()` (`:411-425`) still writes the full form dict — that is correct, it is an
explicit admin save.

## Tests (`class_visit/tests/test_settings_install.py`, new)

1. No row → `install()` creates it with every default key.
2. Configured row (e.g. `report_fields_json` holding real JSON, `visit_types` customised,
   `is_active='Yes'`) → `install()` leaves every configured value byte-identical.
3. A key deliberately blanked (`teacher_submit_message=''`) is **not** re-defaulted.
4. A row missing a newly added key gains it, and the other keys are untouched.
5. Second `install()` on a complete row performs no write (assert with
   `assertNumQueries` or a `save` spy).
6. Non-dict legacy value (e.g. `None` or a string) does not raise, and ends as a dict.

## Notes

- **Not a class_visit-only bug.** `setting.value = defaults` appears in **54** settings
  modules across grades, future_sections, drop_wd, pd_event, mou, student_onboarding,
  instructor_app, cis and others. This plan fixes class_visit; file one tracking issue
  listing the rest so the pattern gets swept rather than forgotten.
- Recovery for an already-wiped tenant is out of scope here: the old value is gone, not
  versioned. Worth saying so in the issue, so nobody looks for an undo.
- Ships first. Every later plan adds settings keys, and each one is exposed to this bug
  until it lands.
