# #6 — Report fields that can express a rubric (narrow version)

## Decision taken

**Narrow, not a rubric builder.** Three additions to the existing field-definition
vocabulary — a heading, per-field help text, and one rating group whose criteria share a
scale. No weights, no scoring, no totals. That is enough for EWU's Site Visit Report
2026-2027 (twelve criteria scored *Excellent / Adequate / Needs Improvement / N/A*, then
five narrative prompts) and stops well short of a general rubric engine.

## Problem (verified)

A field def today is
`{name, label, type, public, required, options, visit_types}`
(`services/report_fields.py:1-13`), with types frozen at
`{text, textarea, select, checkbox, date}` and validated in
`settings/class_visit.py::clean_report_fields_json`.

- `build_report_form_fields` (`services/report_fields.py:93-160`) sets only `label`,
  `required`, `initial` and `widget` — **never `help_text`**, and there is no non-input
  type, so a section heading or an instruction cannot be expressed at all.
- `templates/class_visit/faculty/edit_visit_report.html` renders the whole form as a bare
  `{{ form|crispy }}` — no `FormHelper`, no `Layout`, no `Fieldset`, so bootstrap4's
  default one-field-per-row vertical layout applies.
- `templates/class_visit/letter_body.html` mirrors that: one
  `<th>label</th><td>value</td>` row per field.

So a twelve-criterion rubric renders as twelve unrelated full-width dropdowns with no
heading, no instructions, and no shared scale visible anywhere.

## The three additions

### 1. `type: "heading"` — a non-input def

`{"type": "heading", "name": "sec_instruction", "label": "Instruction"}` plus optional
`"help_text"`. It produces **no form field** and **no meta key**; it is layout only.

Consequences to handle deliberately, because they are where this will break:
- `build_report_form_fields` must skip it (no field, or the POST gains a phantom key).
- `VisitReportDynamicForm.save()` loops `get_report_field_defs()` and writes
  `report.meta[name]` for any name in `data` (`forms/faculty.py:317-322`) — a heading has
  no data, so it must be skipped there too.
- `report_values_for_display` must emit it as a marker (`{'kind': 'heading', 'label': …}`)
  so the letter can render it as a section row rather than an empty label/value pair.
- `public_field_names()` (`services/report_fields.py:86-92`) is a set of names for
  public filtering; a heading is not a value, so decide once: headings always render,
  in both the public and full letter. Simplest and least surprising.
- `clean_report_fields_json` must not demand `options` or `required` for it, and must
  still enforce unique `name` (the meta-key uniqueness rule is what keeps ordering sane).

### 2. `help_text` on any field

One line in `build_report_form_fields`: pass `help_text=defn.get('help_text', '')` to
every branch. Crispy renders it under the input with no template change. In the letter,
help text is an instruction to the writer, not part of the record — **do not** render it.

### 3. `type: "rating"` with a shared scale

```json
{"type": "rating", "name": "rubric_teaching", "label": "Teaching",
 "scale": ["Excellent", "Adequate", "Needs Improvement", "N/A"],
 "criteria": [
   {"name": "rubric_pacing", "label": "Lesson pacing"},
   {"name": "rubric_questioning", "label": "Questioning technique"}
 ]}
```

- Each criterion becomes its own `ChoiceField` over the shared `scale`, so **one meta key
  per criterion** — `rubric_pacing`, `rubric_questioning`. The group's own `name` is a
  layout anchor and stores nothing. Keeping one key per criterion means existing reports,
  exports and `report_values_for_display` keep working unchanged, and a criterion can be
  added later without rewriting stored data.
- `required` may be set on the group and applies to every criterion, or per criterion.
  Whatever #11 decides about draft relaxation applies here too: a relaxed `ChoiceField`
  needs its blank choice added, or a blank draft fails with "not a valid choice".
- Validation additions: `scale` is a non-empty list of unique non-empty strings;
  `criteria` is a non-empty list of `{name, label}`; every criterion name is unique across
  the whole definition list, not just within the group; `options` is rejected on a rating
  group (it is `scale`'s job); `visit_types` on the group applies to all its criteria.

## Rendering

**Form.** Keep `{{ form|crispy }}` for text, textarea, select, checkbox and date. Render
headings and rating groups through a small template that walks the *definitions*
alongside the bound form, so a rating group becomes one table: criteria as rows, the
scale as column headers, radio inputs in the cells. A `FormHelper`/`Layout` would mean
rebuilding the whole form's layout in Python; walking defs in the template keeps the
change additive and leaves ordinary fields exactly as they render today.

At phone width a 12x4 grid does not fit — collapse to stacked radio groups under a
`d-md-none` / `d-none d-md-table` pair rather than letting the table scroll sideways.

**Letter.** `report_values_for_display` gains a `kind` per entry
(`field` / `heading` / `rating`). `letter_body.html` renders headings as a full-width
section row and a rating group as its own small table with the scale as headers and the
chosen value marked. Everything else keeps today's label/value row, so existing tenants'
letters are byte-identical.

## Backward compatibility

Every existing config stays valid: the three additions are new optional keys and two new
`type` values. A tenant that configures none of them sees no change in the form, the
letter or the stored meta. That property is worth a test of its own.

## Tests (`class_visit/tests/test_report_field_rubric.py`, new)

1. A config with no new types produces byte-identical form fields and
   `report_values_for_display` output (the compatibility guarantee).
2. A heading produces no form field, no meta key on save, and no phantom key when posted.
3. `help_text` reaches the rendered form and does **not** reach the letter.
4. A rating group produces one `ChoiceField` per criterion over the shared scale; saving
   writes one meta key per criterion.
5. A criterion name colliding with another field name is rejected at settings save.
6. `scale` empty / non-list / duplicated values → `ValidationError` with a message naming
   the field.
7. `visit_types` on a group filters the whole group in and out.
8. Draft save with a blank rating criterion succeeds once #11 lands (cross-check), and
   submit with it blank fails when required.
9. The letter renders headings as sections and a rating group as a grid; `public_only`
   filtering still excludes non-public criteria while headings still render.
10. A legacy report whose meta predates the rubric still renders (missing keys show blank,
    not `KeyError`).

## Notes and sequencing

- Land **#11** first. The draft-relaxation fix touches the same `ChoiceField` blank-choice
  logic, and doing both at once on the same branch invites a merge that quietly drops the
  blank option.
- The settings field is free-form JSON edited by hand. Twelve criteria written out
  longhand is a lot of JSON to type; the `error_messages` help-text work in #17 (cis) is
  the precedent for documenting the accepted shape inline. Add a worked rubric example to
  the field's `help_text` and to the configuration workbook in the same commit.
- Deliberately **not** in scope: weights, numeric scoring, totals, per-criterion comments,
  conditional criteria, and reordering UI. If any of those come up, they are a second
  issue, not a widening of this one.
