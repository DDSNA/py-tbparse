# Colour palettes

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse).

`py-tbparse style` moves named custom colour palettes between workbooks, `Preferences.tps` files and a small JSON file (`*.style.json`). It saves you from editing `Preferences.tps` by hand when a team shares a corporate palette.

**Read this first.**

- **It only adds palettes to the colour picker. It recolours nothing.** A workbook that already uses colours keeps them exactly: Tableau writes the colour of each value into the datasource, and this tool never touches that. Importing a palette does not change a single mark.
- **Nothing it writes has been opened in Tableau.** The `.tps` shape comes from Tableau's help page ("Create custom color palettes") and from the `<preferences>` block of three public workbooks; no real `Preferences.tps` file was seen. Try the output on a copy, with a backup of your own `Preferences.tps`, before you rely on it. The assumptions nobody has checked are listed at the end of this page.
- **Your files are never modified.** `import` and `export` always write a new file. They never write over the input and never over an existing file named `Preferences.tps`, not even with `--overwrite`. There is no in-place option: you copy the new file into place yourself.

## Where palettes live

- In a workbook: `<workbook><preferences><color-palette name=".." type="..">` with one `<color>#RRGGBB</color>` per colour.
- In `Preferences.tps` (folder `My Tableau Repository`, under Documents): the same element. Restart Tableau Desktop after changing it. Edit Colors shows at most 20 colours per palette.
- Palette types are `regular`, `ordered-sequential` and `ordered-diverging`.
- Not read: the unnamed colour ramps inside a sheet's colour encoding, and Tableau's built-in palettes (`green_10_0` and so on).

## Command line

```bash
py-tbparse style show brand.twb Preferences.tps                      # table of the palettes found (--format csv|json)
py-tbparse style export brand.twb -o acme.style.json                 # or -o acme.tps; also --palette NAME (repeatable), --name, --on-clash, --overwrite
py-tbparse style import acme.style.json Preferences.tps              # the plan only, nothing written
py-tbparse style import acme.style.json Preferences.tps --write      # writes Preferences_palettes.tps beside it
py-tbparse style import acme.style.json report.twbx --write -o report_acme.twbx
py-tbparse style check Preferences_palettes.tps                      # problems in a .tps or .style.json
```

`SRC` and `LIB` can each be a `.twb`, `.twbx`, `.tps` or `.style.json`. The target of `import` is a `.tps`, `.twb` or `.twbx`; the output keeps its extension and defaults to `<name>_palettes.<ext>` beside it. A `.twbx` output keeps every other file of the package as it was.

- `import` writes nothing without `--write`. After `--write` it says that the palettes are in the colour picker and the marks keep their colours. For a `.tps` it adds: copy the file over `Preferences.tps` (keep a backup) and restart Tableau Desktop.
- **Name clashes.** A clash is the same name with different colours (same name, type and colours is "already there" and skipped; names that differ only in case are not a clash, the plan notes them). `--on-clash` is `fail` (default: stop, write nothing, say which names), `skip` (keep the existing one), `rename` (add as `Name (2)`, or the next free number) or `replace` (swap the existing palette in place). Use `replace` for a new version of your palette and `rename` to keep both.
- Palettes that cannot be used (no name, an unknown type, no colours, a colour that is not `#RRGGBB` or `#RRGGBBAA`) are listed as `invalid` and are never written. The command still writes the rest and exits 2.
- Exit codes: 0 fine; 1 an error, a name clash under `--on-clash fail` (also when you only print the plan), or `check` found problems; 2 some palette was invalid but the rest was written. Every command's codes: [cli.md](cli.md#exit-codes).
- Everything else in the target is kept: other `<preference>` elements, unknown elements in a `.tps`, all sheets and formats. A workbook is written again as a whole by the XML library, so quoting and spacing of the whole file can change, as with `rename`.

## In the GUI

The **Styles** view of `py-tbparse-gui` does the same on the open workbook: list its palettes with colour chips and the `check` results, export the ticked ones as a style file or a `Preferences_palettes.tps` (downloads only), and add the palettes of an uploaded `*.style.json` or `.tps` with the clash policy chosen on the page (default `fail`, plan and clash list shown first). It writes nothing on the server, so it never changes the open workbook or your `Preferences.tps`; the result is a download. See [the GUI page](gui.md#styles).

## The style file

`*.style.json` is UTF-8 JSON with sorted keys: `format` (`py-tbparse-style`), `version` (1 or 2, see [Formatting](#formatting-fonts-and-workbook-rules)), `name`, `description`, `created`, `py_tbparse_version`, `sources` and `palettes` (a list of `name`, `type`, `colors` and `attrs`, in source order; `attrs` holds the other attributes of the palette, such as `custom`, as strings). A file with another format, a newer version or an unknown key is refused. A palette-only file is still written as version 1, so existing files and older py-tbparse keep working.

## From Python

`extract_style`, `format_table`, `style_warnings`, `plan_style`, `build_styled`, `apply_style` (formatting, below), `read_palettes`, `palettes_table`, `export_palettes`, `import_palettes`, `plan_palette_import`, `build_with_palettes`, `tps_bytes`, `make_style`, `save_style`, `load_style`, `check_style_file`, and for bytes instead of files `build_export`, `palettes_from_bytes`, `palette_records` and `palette_problems`, all in `py_tbparse` (module `py_tbparse.style`; errors are `StyleError`, a `ValueError`).

## Formatting (fonts and workbook rules)

Slice 2 of the style work (plan: [wp7-style-plan-slice2.md](wp7-style-plan-slice2.md)) moves **name-free formatting**: fonts, workbook style rules and dashboard zone styles. Two packages are built: you can **read** that formatting out of a workbook into a style file (`extract`), and **write the workbook-level part** (fonts and workbook style rules) onto a copy of another workbook (`apply`). Dashboard and sheet formatting is not written yet (later packages), and `import` still ignores every formatting section.

```bash
py-tbparse style extract brand.twb -o brand.style.json     # --dashboard NAME, --scope workbook,dashboards, --no-palettes, --name, --overwrite
py-tbparse style show brand.twb --what formats             # the same, as a table (--format csv|json)
py-tbparse style check brand.style.json                    # also validates the formatting sections
py-tbparse style apply brand.style.json other.twb          # the plan only, nothing written
py-tbparse style apply brand.style.json other.twb --write  # writes other_styled.twb beside it
```

What `extract` reads:

- **Workbook rules**: the workbook's `<style><style-rule>` for `all`, `worksheet`, `title` and `tooltip`. The font attributes (`font-family`, `font-size`, `font-weight`, `font-style`, `color`) go to `fonts`, keyed by element; every other format goes to `workbook_rules`. Only 7 of the 200 corpus workbooks have such a block, so most workbooks give nothing here: fonts usually live on titles, sheets and dashboards instead.
- **Dashboards**: the `zone-style` formats (`background-color`, `border-color`, `border-style`, `border-width`, `margin`, `padding`) summed up **by zone role**: `root` (the zone directly under the dashboard's zones), `container` (other layout zones), `sheet` and `title`. For each role and attribute the most frequent value wins (a tie goes to the first in document order); the attributes that had more than one value are listed as `mixed` and in the `note` column of `show`. So the file is a summary of what the dashboards do, not a record of one zone. The root's background is stored as `dashboard.background`. The dashboards' own `dash-title`, `dash-subtitle` and `dash-text` rules go to `dashboard.rules`. Without `--dashboard` all dashboards of the workbook are pooled.
- **Not read, and counted**: any format with a `field=` attribute, `encoding` children (per-value colours), every `_.fcp.*` feature-flag element, rules for other elements, other zone kinds (filters, text, images, legends), device layouts and sheet formats (the `sheets` scope is a later package and is refused for now).
- **Nothing is invented.** A workbook without such formatting gives empty sections (and a version 1 file when it has no other formatting either). A value that Tableau wrote as boilerplate (`margin 4`, `border none`) is read like any other: the file cannot tell a choice from a default.

The version 2 file adds four optional sections, all values strings exactly as in the XML: `fonts` (`{element: {attribute: value}}`), `workbook_rules` (`[{element, formats: [{attr, value, scope?}]}]`), `dashboard` (`background`, `roles` as `{role: {attribute: value}}`, `rules` like `workbook_rules`) and `sheet_defaults` (like `workbook_rules`; validated, not extracted yet). `fonts` is a view of the same rules as `workbook_rules`, so one (element, attribute) may not be in both, and `dashboard.background` may not be repeated as `roles.root.background-color`. Allowed names are fixed lists in `py_tbparse.style`, and a test compares them with Tableau's schema. Colour attributes are `color` and `background-color` (there is no `font-color`). `check` refuses an unknown role, element or attribute, an empty value, a control character and anything with `_.fcp.` in it. A font family that is not one of the "Tableau *" faces is only a **warning**: it may not exist on the machine that opens the result, and what Tableau does then has not been checked.

### Applying it (`style apply`)

`apply` takes a style file (or any workbook, whose formatting is extracted on the fly) and a `.twb` or `.twbx` target. It prints a plan first, one row per format, and with `--write` saves a copy named `<name>_styled.<ext>`. The input is never modified, an existing output is never replaced without `--overwrite`, and the input itself never.

- **A format the target already has is kept, whatever its value.** There is no marker in the XML that tells a choice from a default Tableau wrote, so even `margin 4` or a font Tableau picked counts as explicit. The plan shows these rows as `skip`, with the target's current value; `--force` replaces them in place (position and other attributes kept). So on a workbook that already sets a font, `apply` will say "kept" and change nothing for that font; this is intended, not a bug. Whether a workbook rule would even show through the sheets' own formats is not known (see the assumptions).
- Actions per format: `add` (absent, written; the `<style>` block or the `style-rule` is created when missing), `same` (already that value; colours compare without case), `skip`, `force`, `unsupported`, `fail`. `--on-clash fail` turns every `skip` into `fail` and writes nothing, which suits CI. `--force` and `--on-clash fail` together are refused.
- **Only the `workbook` scope is written.** Fonts (`fonts`) and `workbook_rules` become `<style><style-rule element=..><format attr=.. value=../>`. A new `<style>` goes after `preferences` (and `style-theme`) and before the datasources; a new rule goes after the last real `style-rule`; a new format goes at the end of its rule. Formats with a `field=`, `encoding` children, `_.fcp.*` elements and every other rule are left as they are. What the file holds for `dashboards` and `sheets` is listed as `unsupported` (work packages 2c and 2d) and makes the exit code 2 after `--write`.
- **Feature-flagged style blocks.** Many Tableau workbooks (90 of the 200 in the corpus) keep their only workbook style as a flagged element `<_.fcp.X.false...style>`. `apply` never edits that element. A format the flagged block already sets (same element, attribute and scope) counts as the target's own: the plan shows its value as `current` and the action is `skip` (`fail` under `--on-clash fail`), or `same` when the value matches, and no plain `<style>` is added for it unless `--force`. With `--force`, and for formats the flagged block does not set, a plain `<style>` is added beside it and the plan and the report say so. How Tableau combines the two is unknown.
- Palettes in the style file are ignored unless `--palettes` is given (then `--palette-on-clash` decides, default `fail`). `.twbx` members other than the workbook are copied untouched. `--dashboard` and `--sheet` take exact names of the target and an unknown name is an error; they only matter once those scopes are written.
- The report after `--write` gives, per scope, applied (added plus forced), same, skipped and unsupported counts, and ends with "formats were added to the workbook; marks keep their colours; nothing here has been opened in Tableau".

## Not covered

Recolouring marks, per-value colours, device layouts, logos and number formats. Those are bound to fields, values or positions in a workbook (`docs/style-model.md` has the evidence). Writing dashboard formatting and the sheet whitelist, the GUI card and template integration are later packages of the slice 2 and 3 plans; `apply` lists them as `unsupported` for now.

## Assumptions nobody has checked in Tableau

1. A `.tps` written like this is read after a restart and its palettes show in Edit Colors.
2. A palette in a workbook's `<preferences>` is offered in that workbook's picker on a machine whose `.tps` lacks it.
3. `custom="true"` is optional, and 8-digit (alpha) colours are accepted in a `.tps` (the tool warns about them).
4. The picker order follows the file order; names are compared case-sensitively; what Tableau does when a workbook palette and a `.tps` palette share a name is unknown.
5. Adding or replacing a palette leaves the marks that use it unchanged (strongly suggested by the corpus, not observed).
6. A `<preferences>` block inserted where the 2026.2 schema puts it also loads in older Tableau versions.
7. A palette named like a built-in one (for example "Tableau 10") does not upset the picker.
8. (Formatting, extract only) The "most frequent value per role" summary is a fair picture of a dashboard; the `all`, `worksheet`, `title` and `tooltip` workbook rules are the ones Tableau reads for Format > Workbook (which element it writes there is unknown); and a workbook `<style>` block that we did not write ourselves is what a later `apply` would imitate. None of this was opened in Tableau.
9. (Applying fonts and workbook rules) A workbook `<style>` or `style-rule` added by py-tbparse is read and applied by Tableau and is not dropped when the workbook is saved; the `all`, `worksheet`, `title` and `tooltip` elements are the ones that carry Format > Workbook; a workbook rule shows through on sheets that have their own formats (Tableau's merge order between workbook, sheet and zone rules is unknown); a plain `<style>` added next to a feature-flagged `<_.fcp.*...style>` is accepted; a font missing on the machine is replaced silently; `font-weight` and `font-style` values copied as strings are valid. Checks 42 and 44 in [tableau-check.md](tableau-check.md) are meant to settle the first of these.
