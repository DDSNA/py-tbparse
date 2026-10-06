# Dashboard scaffolds

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse).

A scaffold is the layout of one dashboard without its sheets: a small JSON file (`*.scaffold.json`) that holds the container tree, the text, title and blank zones, the zone styles, the dashboard size and style, and one numbered slot for every sheet. You can take it from one dashboard and make a new dashboard from it, with your own sheets in the slots, in the same or in another workbook.

**Read this first.** Nothing this writes was ever opened in Tableau Desktop. The output follows what Tableau writes (shapes measured on the 200-workbook test corpus), passes Tableau's published schema without any error the input did not already have, and passes the reference checks described below. That is all that has been checked. Not checked: that Desktop opens it, how it looks, and whether Desktop re-flows the tiled positions when the sheets differ from the originals. Apply a scaffold to a copy and open the copy in Tableau before you rely on it.

## What the first slice does

Make:

- The source dashboard must have **exactly one top-level zone, a tiled `layout-basic` root**. A layout with floating objects (about half of the corpus), an older floating-only layout and a storyboard are refused with a clear message. In the corpus 68 of 135 dashboards qualify.
- Kept: nested containers (`layout-basic`, `layout-flow` with its direction, `is-fixed` and `fixed-size`), text zones with their formatted text, title and blank zones, zone styles, the dashboard `<size>`, `<style>`, title options and `enable-sort-zone-taborder`. Positions are copied as written.
- Every sheet zone becomes a numbered slot (`slot`, the original sheet name as a `hint`, width and height). A sheet zone's own `param` (a set control) is not kept.
- Dropped, and **listed in the scaffold** (`dropped`, shown by `scaffold show`): filters, colour and size legends, parameter controls, images, web pages, buttons, anything else, containers the dropped zones left empty, the dashboard's device layouts (Tableau makes the phone layout again), and the dashboard's data sources and column dependencies. Filters and legends depend on fields the sheets you pick may not have; they come in a later slice.

Apply:

- Always a **new dashboard**; existing dashboards, sheets and windows are not touched. The name must not be used by a worksheet or a dashboard.
- Zone ids are renumbered 1 to n in document order. The dashboard and its window get new `simple-id` uuids (never one already in the workbook). A window is written with one viewpoint per chosen sheet and no active zone (`<active id="-1"/>`, which the schema requires).
- Every slot needs a sheet, every sheet must exist as a worksheet, and a sheet can fill only one slot. Too many, too few, unknown or repeated sheets are errors, never silent changes. `--allow-empty` turns slots without a sheet into blank zones.
- The output is a new file (default `<name>_scaffold.<ext>` beside the workbook), keeps the workbook's extension (a `.twbx` keeps all its other members) and never replaces the input.

## Command line

```bash
py-tbparse scaffold make sales.twb -d "Overview" -o overview.scaffold.json     # -d may be left out when there is only one dashboard
py-tbparse scaffold show overview.scaffold.json                                # slots, and everything that was dropped (--format csv|json)
py-tbparse scaffold apply other.twb overview.scaffold.json --name "Regional" --sheets "Sales,Profit"   # the plan only
py-tbparse scaffold apply other.twb overview.scaffold.json --name "Regional" --sheet Sales --sheet Profit --write
```

`make` takes `--dashboard`, `--output`, `--name`, `--description` and `--overwrite`. `apply` takes `--name`, `--sheet` (repeatable, in slot order), `--sheets` (comma-separated; use `--sheet` when a name has a comma), `--allow-empty`, `-o`, `--overwrite`, `--write` and `--format`. Without `--write` nothing is written. Exit code 1 on any error.

From Python: `make_scaffold(workbook, dashboard)`, `save_scaffold`/`load_scaffold`, `apply_scaffold(workbook, scaffold, name, sheets)` with `sheets` a list or `{slot number: sheet}`.

## Zone kinds and the integrity check

Tableau stores a zone's kind in `type-v2` (newer files), `type` (older ones), or, in 24 zones of the corpus, only in a feature-flag attribute such as `_.fcp.SetMembershipControl.true...type-v2`. `py_tbparse.dashboards.zone_kind()` reads all three (a zone with a name and none of them is a sheet) and is used by `dashboard_summary`, which used to read only the first two. The summary also counts filters and parameter controls in the main layout only, as a device layout repeats them.

`integrity_check(workbook_xml, dashboard=None, require_window=False)` returns the problems it finds (an empty list means none), and the scaffold tests run it on every output. The schema does not check any of this:

- unique zone ids in each layout (a device layout may reuse the main layout's leaf ids);
- every sheet, filter and legend zone names a worksheet or dashboard;
- the window's viewpoints name worksheets, and its active zone exists;
- the dashboard and its window have different `simple-id` uuids, and no uuid is used twice;
- with `require_window`, the dashboard has a window (real workbooks lack one in about one dashboard in nine, so it is off by default).

On the corpus it reports one problem in total: a duplicated uuid in one workbook.

## Not built yet

Replacing the layout of an existing dashboard, filters and legends that follow their slot, buttons and images, floating objects, carrying device layouts over, and keeping scaffolds inside a template.
