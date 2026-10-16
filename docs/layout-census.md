# Layout census of the corpus (WP0 of #84)

Numbers for the layout preview planned in `docs/plan-84-layout-preview.md`, measured on the 200 workbooks of
`tests/corpus/files` with `scripts/layout_census.py`. Only the **main layout** of each dashboard is read (device
layouts are left out, as in `dashboard_layout`). The output holds counts only: no workbook, sheet, dashboard or
zone name. Re-run it any time the corpus changes:

```bash
python scripts/fetch_corpus.py
nice -n 10 ionice -c3 timeout 900 python scripts/layout_census.py --log census.log --stop-file census.stop > census.md
```

Limits of the script: one worker; `--timeout` seconds per file (Unix only; a parse inside lxml is not interrupted
until it returns); files over `--max-mb` (20) are skipped; `--cap N` reads at most N files; creating the `--stop-file`
ends the run after the current file; it waits while free memory is under 1.5 GB or the load average is over 3.5, and
stops if it uses over 1.2 GB or the log folder has under 200 MB free. It prints its peak memory and the highest load
seen. This run (2 CPUs, another job running at the same time): 200 files in about 10 seconds, peak memory 23 MB as
reported by `ru_maxrss`, load average 1.3 to 1.6 throughout, nothing skipped.

Definitions. A **leaf** is a zone with no child zone and not a `layout-basic`/`layout-flow` container (the cards also
drop containers). **Placed** is a leaf with a full `x, y, w, h` and `w, h > 0`. Two placed leaves **overlap** when
their shared area is more than 1% of the smaller one (`--min-overlap`). The corpus has **no** explicit floating attribute
on any zone (attribute names containing "float" were searched), so "floating" cannot be measured directly; the census
also counts leaves that sit directly in a `layout-basic` container that is not the root zone, as a proxy, because
that is where Tableau keeps free-placed items. The proxy is an assumption and is not checked against Tableau.



## The numbers

### Files and dashboards

|  | count |
|---|---|
| workbooks read | 200 |
| skipped: over size limit | 0 |
| skipped: unreadable or timed out | 0 |
| with no dashboards | 92 |
| dashboards | 135 |
| dashboards with no leaf zones at all | 5 |

### Leaf zones per dashboard (containers not counted)

| leaf zones | dashboards |
|---|---|
| 0 | 5 |
| 1 | 13 |
| 2 | 13 |
| 3-5 | 41 |
| 6-10 | 43 |
| 11-20 | 19 |
| 21-40 | 1 |

### Leaf zones: summary

|  | value |
|---|---|
| maximum | 40 |
| median | 5 |
| total | 821 |
| dashboards over 40 (the card sketch cap) | 0 |
| dashboards over 200 (the preview cap) | 0 |
| zones (containers included), maximum on one dashboard | 59 |

### Odd sizes and positions (leaf zones; all counted separately)

| case | zones | dashboards | of dashboards |
|---|---|---|---|
| no full x, y, w, h | 10 | 1 | 0.7% |
| w or h zero or negative | 0 | 0 | 0.0% |
| x or y negative | 5 | 3 | 2.2% |
| x or y past 100000 | 0 | 0 | 0.0% |
| x+w or y+h past 100000 | 21 | 11 | 8.1% |
| sticks out of its parent container's rectangle | 0 | 0 | 0.0% |

### Overlap (pairs of placed leaf zones sharing more than 1% of the smaller one)

| pairs where | pairs | dashboards | of dashboards |
|---|---|---|---|
| any (total) | 255 | 39 | 28.9% |
| one zone has an explicit floating attribute | 0 | 0 | 0.0% |
| no floating attribute, one zone sits in a non-root layout-basic container | 70 | 14 | 10.4% |
| neither | 185 | 31 | 23.0% |

### Shape of the overlap (same pairs, split another way)

| pairs where | pairs | dashboards | of dashboards |
|---|---|---|---|
| the two rectangles are identical | 0 | 0 | 0.0% |
| one rectangle lies completely inside the other | 96 | 25 | 18.5% |
| they cross each other only partly | 159 | 26 | 19.3% |
| one of the two is a text or image zone | 111 | 14 | 10.4% |

### Floating and nesting

|  | value |
|---|---|
| leaf zones with an explicit floating attribute (is-floating, floating) | 0 |
| leaf zones directly in a non-root layout-basic container | 210 |
| nesting depth: maximum | 16 |
| nesting depth: median | 4 |
| dashboards nested deeper than 6 | 14 |
| containers in total | 513 |

### Extent against the grid and the dashboard size

|  | dashboards |
|---|---|
| with placed zones | 129 |
| extent past 100000 in x or y | 11 |
| extent under 99% of 100000 in x or y (drawing would not fill a square-grid frame) | 37 |
| with a fixed pixel size (min equals max) | 78 |
| fixed size and extent past 100000 (positions may be pixels) | 7 |

### Smallest zones at 500 px wide

|  | zones | of placed leaves |
|---|---|---|
| narrower than 40 px (letter instead of a name) | 38 | 4.7% |
| narrower than 5 px (nothing readable) | 12 | 1.5% |
| dashboards with at least one zone narrower than 40 px | 21 | 15.6% |

Narrowest zone per dashboard, px at 500: minimum 0.50, median 80.00, maximum 500.00.

Run: peak memory 23 MB, highest load seen at file starts 1.39.

## What this means for the later packages

- **Zone cap.** The largest dashboard has 40 leaf zones (59 zones with containers); none is over the card cap of 40
  or the preview cap of 200. The cap of 200 is safe for every workbook in the corpus, with a factor of 5 to spare.
  Real workbooks outside the corpus may differ; the corpus is public example files, not a sample of any company's.
- **Overlap is common.** 39 of 135 dashboards (29%) have at least one overlapping pair of leaves, 255 pairs in all.
  The plan said that if it is common the plan changes before WP2: the drawing needs an order and the list a hint. About
  a third of the pairs have one rectangle completely inside the other (a small zone on a bigger one, as floating zones are);
  the rest cross only partly. Draw larger zones first and smaller ones on top, and keep outlines visible, so nothing is
  hidden entirely. A "covers / is covered by" note in the list is worth having for these dashboards.
- **No floating attribute in the corpus.** So WP2 cannot get a floating rule from this data; the nested pairs are the
  closest evidence. Whether Tableau draws them as the sketch does stays unverified (nothing here was compared with
  Tableau Desktop).
- **Grid.** 11 of 129 dashboards with placed zones have `x+w` or `y+h` past 100000 (21 zones; 7 of those dashboards have
  a fixed pixel size), 3 have a negative `x` or `y` (5 zones), none has a start past the grid. So the grid is **not**
  safe to assume: the extent must be taken from the zones (as the cards already do) and negative starts clamped or
  included in the viewBox. Those zones are still positions as stored; whether they are pixels is not known.
- **Missing sizes.** One dashboard has leaves without a full position (10 zones); none has zero or negative `w`/`h`.
  The "N zones have no stored position" line is needed but rare.
- **Names that fit.** At 500 px wide 38 of 821 placed leaves (4.7%) are under 40 px, in 21 dashboards, and 12 (1.5%)
  under 5 px. The letter fallback is used by a small minority; the 5 px ones are invisible and only the list shows them.
- **Nesting.** Median depth 4, deepest 16, 14 dashboards deeper than 6. Containers are 513 of 1,334 zones. Leaves are
  never outside their parent container's rectangle, so flat drawing of leaves at their stored position will not push
  children out of their containers. Padding and margins inside containers were not measured.
- **Dashboards without leaves.** 5 dashboards have no leaf zone at all (empty state), and 92 of the 200 workbooks have
  no dashboard.

## What was not measured

- Whether the overlap is real in Tableau. The 159 partial crossings may come from how Tableau stores a layout (padding,
  floating items in a `layout-basic`, positions relative to a parent) and not from zones that visibly cover each other;
  the census does not tell which. A reading of what these pairs are (kinds, sizes) is still open.
- Floating zones by attribute (none exist in the corpus), pixel versus grid units of floating positions, drawing order
  as Tableau uses it, container padding and inner margins.
- Phone and tablet layouts (left out), the `<size>` of automatic-size dashboards, and any dashboard outside the 135.
- Text length of zone names (the names are not read), so how many names are too long for their zone is not known;
  only the zone width at 500 px was measured.
- Speed or memory on a large workbook: no file over 20 MB is in the corpus, so the size skip is tested on a small
  limit only.
