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
- Exit codes: 0 fine; 1 an error, a name clash under `--on-clash fail` (also when you only print the plan), or `check` found problems; 2 some palette was invalid but the rest was written.
- Everything else in the target is kept: other `<preference>` elements, unknown elements in a `.tps`, all sheets and formats. A workbook is written again as a whole by the XML library, so quoting and spacing of the whole file can change, as with `rename`.

## The style file

`*.style.json` is UTF-8 JSON with sorted keys: `format` (`py-tbparse-style`), `version` (1), `name`, `description`, `created`, `py_tbparse_version`, `sources` and `palettes` (a list of `name`, `type`, `colors` and `attrs`, in source order; `attrs` holds the other attributes of the palette, such as `custom`, as strings). A file with another format, a newer version or an unknown key is refused.

## From Python

`read_palettes`, `palettes_table`, `export_palettes`, `import_palettes`, `plan_palette_import`, `build_with_palettes`, `tps_bytes`, `make_style`, `save_style`, `load_style` and `check_style_file`, all in `py_tbparse` (module `py_tbparse.style`; errors are `StyleError`, a `ValueError`).

## Not covered

Recolouring marks, fonts, borders, dashboard styling, device layouts, logos and number formats. Those are bound to fields, values or positions in a workbook (`docs/style-model.md` has the evidence); this release does only the palette library.

## Assumptions nobody has checked in Tableau

1. A `.tps` written like this is read after a restart and its palettes show in Edit Colors.
2. A palette in a workbook's `<preferences>` is offered in that workbook's picker on a machine whose `.tps` lacks it.
3. `custom="true"` is optional, and 8-digit (alpha) colours are accepted in a `.tps` (the tool warns about them).
4. The picker order follows the file order; names are compared case-sensitively; what Tableau does when a workbook palette and a `.tps` palette share a name is unknown.
5. Adding or replacing a palette leaves the marks that use it unchanged (strongly suggested by the corpus, not observed).
6. A `<preferences>` block inserted where the 2026.2 schema puts it also loads in older Tableau versions.
7. A palette named like a built-in one (for example "Tableau 10") does not upset the picker.
