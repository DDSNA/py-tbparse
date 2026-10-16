# Design options for #84: cards and layout preview in the Dashboards view

Mockups only. Nothing here is wired into the app; the data is made up. The pages link the app's own
`tokens.css`, so they follow the real colours, spacing and type. Open them from a checkout.

| | Option A: cards | Option B: table plus layout panel |
|---|---|---|
| Page | [option-a-cards.html](option-a-cards.html) | [option-b-preview-panel.html](option-b-preview-panel.html) |
| Picture | [option-a-cards.png](option-a-cards.png) | [option-b-preview-panel.png](option-b-preview-panel.png) |

## What is already there

The Dashboards table has the counts (`worksheets`, `filters`, `parameters`, `actions`, `images`, `texts`, `webs`)
and the names (`filter_fields`, `parameter_names`). The overview already has a small `dash-card` (name and
first six sheet names). What #84 still lacks is a per-dashboard card in the Dashboards view and a layout
preview. The preview needs the position of every zone, not only worksheet zones: `dashboard_sheets()` returns
only sheets, so either option needs one small new function returning all zones of the main layout with kind,
x, y, w, h.

## Option A: one card per dashboard

A grid of cards, one per dashboard, with a **Cards / Table** switch (the table stays one click away). Each
card has a small layout sketch, count chips (worksheets, filters, parameters, actions, images, texts, web
pages), the sheet, filter and parameter names, and a link that opens Dashboard sheets filtered to it.

- Good: everything about every dashboard is visible at once; reads like a summary page; extends the existing
  overview card, so the look is already settled; phone layout is a single column.
- Weak: the sketch is tiny (about 150 px), so zone names do not fit, only a letter per zone; a workbook with
  dozens of dashboards means a long page; the same facts sit in two places (cards and table).
- Effort: medium. A server-side zone list, a card renderer in `app.js`, about 40 lines of CSS, a view switch
  that remembers its state, and browser tests (cards, switch, narrow width, keyboard).
- Risks: card count. Draw cards in pages of 24 to 50 like the Slice view does, never all at once, or a
  workbook with hundreds of dashboards makes a big DOM. The sketch must be built from at most a few dozen
  zones per dashboard; cap it and say so. A dashboard with no stored positions needs an empty state.

## Option B: table with a layout panel

The table is unchanged. Selecting a row opens a panel beside it (under it on a narrow window) with a large
layout drawing, the name on each zone, and a list of every zone with its kind and position. Hovering a zone
or a list line highlights the other. Buttons: show in Dashboard sheets, copy the zone list.

- Good: the preview is big enough to read names; the table keeps sorting, filtering, column options and CSV
  export, and its rows stay virtual, so the number of dashboards does not matter; only one drawing is ever in
  the DOM; the zone list is useful on its own for finding a filter or web zone.
- Weak: you see one dashboard at a time, so no overview of all of them; the panel needs a free half of the
  screen, so the table gets narrow; filter and parameter names are not on the card, only in the table
  columns (they could be added to the panel header).
- Effort: medium to large. The same server-side zone list, a panel with SVG drawing, linked hover and
  selection, a responsive split, focus handling (the panel is not a dialog, so no focus trap), and more
  browser tests than A.
- Risks: interplay with the existing row drawer, which already opens on row click or Enter; the panel would
  have to replace it for this table or live beside it, which is a decision for the owner. Keyboard and screen
  reader use need the zone list as the real content, with the drawing marked decorative.

## Common to both

- Main layout only, as the counts already are; phone and tablet layouts are not drawn.
- Drawn from `x, y, w, h` of zones. Nested containers and floating zones are drawn flat at their stored
  position; that has not been checked against the 135 corpus dashboards, so overlap and odd sizes are
  unknown until it is.
- Zone kind is shown by letter and outline style as well as colour, in light and dark themes.
- Neither mockup was checked with a screen reader, in dark mode, or in the other colour themes. The
  screenshots are Chromium at 1360 px; at 375 px the pages have no sideways scroll.

## Questions for the owner

1. A (overview of all dashboards) or B (one big, readable preview)? Doing A first and B later is possible:
   both need the same zone list.
2. For B: should the panel replace the row drawer on the Dashboards table, or sit next to it?
3. For A: is the Cards view the default for this table, or does the table stay the default?
