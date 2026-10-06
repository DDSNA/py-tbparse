# Style model: where style lives in a Tableau workbook

WP7 phase 0 findings. Part of [py-tbparse](https://github.com/DDSNA/py-tbparse). Evidence, not a plan.

Method: `scripts/style_census.py` (stdlib + lxml, read-only) over the 200-workbook public corpus
(`tests/corpus`, 758 worksheets, 135 dashboards, 296 datasources). Re-run with
`nice -n 10 timeout 300 python scripts/style_census.py [--examples]`; it prints every table quoted below.
"Wbs" = number of workbooks (of 200) with at least one. The corpus is public GitHub material, so it leans to
demos, tutorials and Superstore copies; treat frequencies as indicative, not as a market survey.

## 1. Totals: how much is set explicitly

| fact | count |
|---|---|
| worksheets with explicit `table/style` rules | 465 of 758 |
| worksheets with explicit pane `style` rules | 450 of 758 |
| dashboards with any `zone-style` | 109 of 135 |
| dashboards with dashboard-level `<style><style-rule>` | 23 of 135 |
| workbooks with a workbook-level `<style>` | 7 (rules: worksheet 3, all 3, title 2, tooltip 2, animation 1, story-title 1) |
| workbooks with a `<preferences><color-palette>` | 3 |
| datasources with a `<style>` | 109 in 98 workbooks (all contain only `mark` colour encodings) |

"Explicit" here means "present in the XML". Tableau writes many rules whenever a user touches anything
(e.g. `mark-labels-show`, `border-style=none`, `margin=4`), so presence is not proof of a deliberate choice.
The corpus cannot separate deliberate from boilerplate; a default has no marker in the file.

## 2. Element catalogue

Risk key: **low** = name-free, copy as-is; **med** = name-free but interacts with content or Tableau version;
**high** = references fields/sheets/datasources or data values, needs a mapping or must not be copied.

| element and scope | wbs | name-free? | risk | notes |
|---|---|---|---|---|
| `workbook/preferences/color-palette` (custom palette, `name`, `type`, `<color>` list) | 3 | yes | **low** | the only palette store that is portable; see section 3 |
| `workbook/style/style-rule element=worksheet/all/title/tooltip` | 7 | yes | low-med | workbook-wide fonts and colours; rare, so little evidence of how Tableau merges with sheet rules |
| `workbook/style-theme name="modern"` | 1 | yes | med | one occurrence; semantics unverified |
| `workbook/document-format-change-manifest` (`_.fcp.*` flags) | 171 | yes | **do not touch** | version feature flags, not user style; also puts `_.fcp.X.true...style-rule` elements in namespaced tags |
| `datasource/style/style-rule element=mark` with `<encoding attr=color type=palette field=...><map to=#hex><bucket>"Central"</bucket>` | 98 (192 encodings, 194 with `<map>`) | **no** | **high** | per-field, per-value colour assignment; field name and data values baked in. `palette="Company DARK"` on the encoding names a palette (built-in id or the workbook's custom one) |
| `datasource/column@default-format` | 37 | no (per column) | high | number formats belong to fields, not to a style |
| `worksheet/table/style/style-rule element=axis,cell,header,label,mark,gridline,zeroline,refline,table,title,...` (24 distinct elements) | up to 100 per element | partly | med | the "sheet formatting" block; see below |
| `... format` with only `scope="rows|cols"` | most of the 1711 rules | yes | low-med | e.g. `<format attr="line-visibility" scope="cols" value="off"/>`; refers to shelf position, not a name |
| `... format` with `field="[ds].[sum:Sales:qk]"` | 95 | **no** | **high** | 680 of 1711 sheet rules contain a `field` attribute (text-format, width, height, color, font-size, title, display...) |
| `worksheet/table/style/style-rule/encoding` (`interpolated`, `custom-interpolated`, `space`, `centersize`, `palette`) | 79 / 48 / 10 / 28 | no (`field`) | high | continuous colour ramps. `custom-interpolated` embeds an inline `<color-palette custom="true" name="">` |
| `worksheet/table/panes/pane/style/style-rule element=mark,pane,cell,trendline,datalabel` | 136 | mostly yes | med | mark size, label show/cull, stroke; `mark-labels-range-field` and encodings name fields |
| `worksheet/layout-options/title/formatted-text/run` (sheet title text and font) | 111 | text may embed `<[ds].[field]>` | med | style (font, size, colour) is name-free, the text is not |
| `dashboard/style/style-rule` (`table`, `dash-title`, `dash-text`, `dash-subtitle`, `parameter-ctrl`, `story-point-caption`) | 23 | yes | low | rare; carries background-color, color, font, text-align, width |
| `dashboard//zone/zone-style/format` (border-color, border-style, border-width, margin, padding, background-color) | 88 wbs, 1455 zones | yes (the style); the parent zone names a sheet | **low** for the format values, **high** if you copy zones | 6598 formats |
| dashboard `title` zone (`type-v2="title"`) | 26 | yes | low | style lives in its `zone-style` and the sheet/dashboard title text runs |
| dashboard `bitmap` zone (logo/image), `param` = image path | 13 (30 zones) | path is machine-local | **high** | example: `param="C:/Users/<name>/Downloads/imgfff.png"`; inside a `.twbx` the image is a packaged file, so copying needs asset handling |
| `dashboard/devicelayouts/devicelayout name=Phone` | 82 wbs (98 layouts, 97 `auto-generated=true`) | **no** | **high** | duplicates a zone tree that names sheets (`name="Sheet 1"`), filters and parameters (`param="[ds].[Action State]"`). Almost all are auto-generated, so regenerate rather than copy |
| `dashboard/size` (fixed/automatic/range) | 56 | yes | med | layout, not style; changes canvas |
| `window/device-preview` | 5 | yes | low | editor state only |

### Sheet style-rule elements, by popularity (wbs having each)
mark 77+135 (table+pane), cell 67, label 46, header 45, worksheet 42, table 33, refline 30, gridline 29, pane 28,
zeroline 24, table-div 21, dropline 18, legend-title-text 17, quick-filter 15, title 14, legend 11. About 30 more
appear in 1 to 10 workbooks. Longest tail of format attrs: `enabled`, `line-visibility`, `stroke-size`,
`text-format`, `font-size`, `font-weight`, `border-*`, `background-color`, `color`, `width`, `height`.

### Raw XML, one short example per element

```xml
<!-- workbook preferences palette -->
<preferences><color-palette name="TableauGen Theme" type="regular"><color>#1A3A5C</color><color>#C9973A</color>...</color-palette></preferences>
<!-- inline custom ramp inside a colour encoding -->
<color-palette custom="true" name="" type="ordered-sequential"><color>#f1f1f1</color>...<color>#d5d500</color></color-palette>
<!-- datasource mark colours: name- and data-bound -->
<datasource><style><style-rule element="mark"><encoding attr="color" field="[none:Region:nk]" type="palette">
  <map to="#4e79a7"><bucket>"Central"</bucket></map>...</encoding></style-rule></style></datasource>
<!-- sheet format, field-bound vs scope-bound -->
<format attr="text-format" field="[Sample - Superstore].[sum:Sales:qk]" value='c"$"#,##0;("$"#,##0)'/>
<format attr="line-visibility" scope="cols" value="off"/>
<!-- dashboard zone -->
<zone name="Sheet 1" ...><zone-style><format attr="border-color" value="#000000"/><format attr="border-style" value="none"/><format attr="margin" value="4"/></zone-style></zone>
<zone h="9524" param="C:/Users/.../imgfff.png" type-v2="bitmap" .../>
<!-- dashboard-level and workbook-level -->
<dashboard><style><style-rule element="story-point-caption"><format attr="width" value="180"/></style-rule></style>
<style-theme name="modern"/>
<devicelayout auto-generated="true" name="Phone"><size sizing-mode="vscroll" .../><zones>...</zones></devicelayout>
```

## 3. Palettes in detail

`<color-palette>` occurrences in the corpus:

| parent | type | custom attr | count | wbs |
|---|---|---|---|---|
| `preferences` (workbook-wide, named) | regular | none | 1 | 1 |
| `preferences` | regular | true | 1 | 1 |
| `preferences` | ordered-sequential | none | 1 | 1 |
| `encoding` (inline, name empty) | ordered-sequential | true | 10 | 7 |
| `encoding` (inline, name empty) | ordered-diverging | true | 9 | 5 |

- Names of the three workbook palettes: "TableauGen Theme" (8 colours), "Retail Teal" (5), "Company DARK" (9).
  So only 3 of 200 workbooks (1.5 percent) carry a named custom palette. Named palettes are rare; this is a
  fact about public demo workbooks and says little about corporate practice.
- Inline encoding palettes have no name, 11 colours in 15 of 19 cases (stepped/continuous ramps). They belong to one field's
  colour encoding and cannot be reused by name.
- A workbook palette is used by name: `<encoding attr="color" field="[none:Segment:nk]" palette="Company DARK" type="palette">`.
  5 of 5 uses in the corpus sit next to a per-value `<map>`, so the palette name is a label while the actual hex
  per value is written out in the datasource style. Choosing a palette in Tableau therefore bakes colours into the file.
- Built-in palette ids referenced by `palette=` (not defined in the file): `sunrise_sunset_diverging_10_0` (11 wbs),
  `green_10_0`, `red_10_0`, `blue_10_0`, `color_blind_10_0`, `traffic_light_10_0`, `tableau-red-blue` ... These need
  no definition and must not be copied as palettes.
- Colour counts: 5, 8, 9, 11 (x15), 13 (x2), 19, 23.

### Preferences.tps

Tableau's `Preferences.tps` (in `My Tableau Repository`) uses the same element:
`<workbook><preferences><color-palette name=".." type="regular|ordered-sequential|ordered-diverging"><color>#RRGGBB</color>...`.
Status: **verified from Tableau's help page** "Create custom color palettes" (fetched 2026-10-05, summarised by a
fetch tool, not checked against a real `.tps` file on a machine). Also from that page: hex colours only, Edit
Colors shows at most 20 (more allowed in the file), restart Tableau Desktop to see changes. Corpus evidence agrees
that a `.twb` `<preferences>` palette has the identical shape (the workbook root is also `<workbook>`).
Not verified here: whether Tableau copies a `.tps` palette into the workbook when used, or only references it.
The corpus suggests it writes the palette into `<preferences>` (the 3 workbooks) and hex per value into
the datasource mark encodings. Unverified: how Tableau treats a palette in the file whose name clashes with a `.tps` one;
whether `custom="true"` is required on a `.tps` palette (corpus has it present and absent in `<preferences>`).

## 4. Fonts actually used

No workbook-level `font-family` appears except in 2 of the 7 workbooks that have a workbook `<style>`. Fonts live almost
only at the leaf:

| where | families (wbs) |
|---|---|
| title / label text runs (`<run fontname=..>`) | Tableau Bold 25, Benton Sans Book 14, Tableau Semibold 5, Tableau Medium 3, Tahoma 3, Times New Roman 2, Arial 2, Verdana 2, Tableau Book 2, Segoe UI 2, plus ~25 singletons (Impact, Cambria, Trebuchet, a CJK face, Google Sans, `-apple-system`) |
| sheet `table/style` `font-family` | Tableau Bold 5, Semibold 4, Medium 4, Tahoma 2, Book 2, Franklin Gothic Book, Times, Arial Black, Cambria |
| pane / dashboard style | Tableau Semibold, Segoe UI, Times New Roman (1 to 2 wbs each) |

Sizes: runs most often 12 (16 wbs), 10 (13), 11 (12), 15, 14, 16, 22, 18, 8; sheet `font-size` 10 (13 wbs), 12 (11), 8, 9, 11.
Font names are system-dependent ("Tableau *" faces ship with Tableau; Tahoma, Segoe, Benton Sans may be missing elsewhere,
and Tableau substitutes silently). Transferring a font name is safe XML-wise; whether it renders is not checkable here.

## 5. Dashboard style details

zone-style values (nearly all Tableau boilerplate):
leaf sheet zones: border-style none 669 of 709, border-width 0, margin 4 (691), padding 0 (402); layout containers: margin 8 (190);
title zones: margin 4, padding 0, `background-color` in 5 (`#f5f5f5`); `background-color` appears on leaf zones in only 6 workbooks
(45 zones, e.g. `#f5f5f5`, `#ffffff`, `#ffaa00`, `#182f1a`) and on layout containers in 9 zones. So a dashboard
background is not a dashboard attribute: it is a `background-color` format on the root or container zone's `zone-style`.
Dashboard-level padding/margin: the container margin (8) and per-zone padding. A "style guide" dashboard would carry these
values on its zone-style elements; mapping zone-for-zone to a target dashboard needs zone `type-v2` and position, not names.

Logo/image: `bitmap` zones hold only a `param` path (absolute local path in the corpus example) plus x/y/w/h, so a
logo is content plus layout, not style. Title: `title` zones (26 wbs) contain no text themselves (title text is in the dashboard's
layout-options/title or sheet titles). Neither is name-bound, but both are positioned inside a zone tree.

## 6. What the corpus cannot tell us

- How Tableau merges workbook-, sheet- and zone-level rules, and which wins on conflict (no ground truth, only files).
- Which values are defaults versus choices (no default marker; rules are written once a control is touched).
- Whether Tableau Desktop opens a modified file cleanly; the corpus is read-only evidence. Nothing here was opened in Tableau
  (`docs/verify-in-tableau.md` describes the manual check).
- Real `Preferences.tps` files; only the help page and 3 workbook palettes were seen.
- Server/Cloud behaviour, version differences (workbooks span many versions; `_.fcp.*` flags show version drift), `.twbx`
  asset handling for images (the corpus is `.twb` only), and corporate "style guide workbooks": none in the corpus.
- Fonts: availability on a target machine.

## 7. Summary of findings

1. **Palettes are the only fully portable style object.** `<color-palette name type><color/>` is name-free, identical in a `.twb`
   `<preferences>` block and in `Preferences.tps` (help page, verified; real .tps file not seen), and has three types.
2. **But palettes are rare in the corpus:** 3 of 200 workbooks define a named palette, 10 more carry unnamed inline ramps.
   The value case rests on the Tableau help documentation and on the effort of hand-editing .tps, not on corpus frequency.
3. **Palette export from a workbook is cheap; applying one is shallow.** Writing a palette into `<preferences>` makes it
   selectable but does not recolour anything: colours in use are baked per value into the datasource `mark` encodings.
4. **Per-value colour maps (`encoding/map/bucket`) are data-bound** (field names and member values; 98 wbs). Never transfer
   without a field and value mapping; recolouring existing marks is a separate, risky feature.
5. **Sheet formats are mixed:** about 40 percent of sheet table rules (680 of 1711) carry a `field=` reference to a
   datasource field instance; scope-only formats (`scope=rows|cols`) and element-wide formats (fonts, colours, borders on
   `header`, `label`, `title`) are name-free. A safe subset is "name-free formats of a whitelist of elements".
6. **Dashboard zone-style is name-free and mostly boilerplate** (margin 4/8, border none). Real styling is few:
   background colours (6 wbs), borders (about 30 zones). Zone style is safe to copy only by zone role (title, container, sheet), not by id.
7. **Device layouts, bitmap/logo zones and datasource column formats are not style-transferable:** the first duplicates
   sheet-naming zone trees (97 of 98 auto-generated, so regenerate), the second holds local paths/assets, the third is per field.
8. **Workbook-level `<style>` is almost unused (7 wbs)** and fonts live on leaves (title runs, sheet rules). A "workbook font"
   feature would therefore write rules Tableau itself rarely produces; behaviour unverified.
9. **Never touch `document-format-change-manifest` / `_.fcp.*` elements:** version flags (171 wbs), not style; they also
   appear as namespaced tags that naive XPath on `style-rule` misses.
10. **First slice: confirm Preferences.tps palette export/import, with two qualifiers.** It is the only name-free, no-risk,
    visible-value item and needs no Tableau-merge semantics. Challenge: do not promise that existing sheets change colour, and
    scope it as "palette library for the colour picker" (export from `<preferences>` of a workbook, import into a `.tps` or a workbook).
    Corpus has no `.tps`, so test fixtures must be built from the help-page schema.
11. **Second slice candidate:** dashboard zone-style by role plus a whitelist of name-free sheet formats (fonts, colours, borders),
    using explicit-vs-skip reporting; needs the "what counts as user-set" question answered first (finding 5 and section 6).
12. Reproduce with `scripts/style_census.py`; all counts are from the 200-file corpus and are indicative only.
