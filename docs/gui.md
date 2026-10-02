# Browser GUI

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse).

```bash
py-tbparse-gui workbook.twb               # opens your browser with it loaded
py-tbparse-gui                            # starts empty: drop a file on the page, pick one, or paste a path
py-tbparse-gui --no-browser --port 8765   # server only, for a machine with no display
```

It uses only the standard library, so there's nothing more to install.

Open a workbook three ways: drop a `.twb`/`.twbx` anywhere on the page, press **Open file...**, or paste a path and Load. A dropped or picked file is copied to a private temporary folder (up to 200 MB, deleted when you open another or quit), so it has no folder to save beside: the Field renames view offers Download instead of Create. Opened paths are listed on the start screen. The **Theme** button switches between 36 colour themes and Auto, Light or Dark. Shop is the default; Matcha, Fjord, Pastel, Neon and High contrast came next, and thirty more are named for what they look like (Harbor, Meadow, Lagoon, Slate, Graphite, Paper, Glacier, Pine, Olive, Citrus, Ocean, Cobalt, Navy, Midnight, Rose, Berry, Mint, Jade, Moss, Steel, Mono, Ink, Frost, Birch, Peacock, Marine, Canopy, Tide, Cornflower and Spruce). Every theme, in light and dark, passes the same contrast tests as the default.

The sidebar lists every table with its row count. Tables stay fast however big they are: only the rows you can see are drawn, so 50,000 rows filter in about 20 ms. Click a column header to sort, type in the filter box to narrow rows (`/` jumps to it), and click a row (or press Enter on it) to open a drawer with every column in full, the real datasource id, and a button that copies the row as JSON. Each column has an options menu (the `...` button, or Alt+Down on a header) to sort, filter just that column, pin it to the left, hide it, change its width or copy its values; the **Columns** button brings hidden ones back, and **Compact rows** fits more on screen. Datasources show their caption instead of Tableau's internal id (hover for the id). The overview opens with a sentence about the workbook, its tiles, a **Worth a look** list (relationships that point at nothing, calculations that name fields the workbook does not have, calculations and fields no worksheet uses; each has a Show button that opens that table already filtered to exactly those rows) and what is on each dashboard. The graph view draws joins and relationships as a picture: drag to pan, scroll or the + and - buttons to zoom, hover or Tab to a table to light up its connections (arrow keys move between tables, Enter tells about one, clicking a line shows its keys), **View as list** for a plain table of the same connections, and **Save as SVG**. A big workbook is drawn one connected group at a time. The DOT text is still there, collapsed under the picture, and **Export DOT** downloads it. The Field renames view has the buttons for the feature above: pick a style, datasource and optional reference workbook, then **Create fixed workbook** saves `<name>_renamed` beside the original (and says so if that file already exists) or **Download fixed workbook** sends it to your browser without saving anything. Everything else exports as CSV. It has a dark theme and works in a narrow window.

![py-tbparse GUI, Field renames view with suggested clean names](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/gui-field-renames.png)

![py-tbparse GUI, the relationship graph with one table and its connections highlighted](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/gui-graph.png)

![py-tbparse GUI, the Neon dark theme with the theme menu open](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/gui-themes.png)

The screenshots are of a made-up demo workbook (`docs/demo/coffee-shop.twb`, built by `scripts/make_demo_workbook.py`); `scripts/readme_screenshots.py` retakes them.

It's meant to run on your own machine for one person. It refuses requests that come from other websites, but there's no login, so don't put it on a shared network.
