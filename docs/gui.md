# Browser GUI

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse).

```bash
py-tbparse-gui workbook.twb               # opens your browser with it loaded
py-tbparse-gui                            # starts empty: drop a file on the page, pick one, or paste a path
py-tbparse-gui --no-browser --port 8765   # server only, for a machine with no display
```

It uses only the standard library, so there's nothing more to install.

Open a workbook three ways: drop a `.twb`/`.twbx` anywhere on the page, press **Open file...**, or paste a path and Load. A dropped or picked file is copied to a private temporary folder (up to 200 MB, deleted when you open another or quit), so it has no folder to save beside: the Field renames view offers Download instead of Create. Opened paths are listed on the start screen. The **Theme** button switches between 34 colour themes and Auto, Light or Dark. Shop is the default, then Matcha, Fjord and High contrast, and thirty more named for what they look like (Harbor, Meadow, Lagoon, Slate, Graphite, Paper, Glacier, Pine, Olive, Citrus, Ocean, Cobalt, Navy, Midnight, Rose, Berry, Mint, Jade, Moss, Steel, Mono, Ink, Frost, Birch, Peacock, Marine, Canopy, Tide, Cornflower and Spruce). Every theme, in light and dark, passes the same contrast tests as the default.

The sidebar lists every table with its row count. Tables stay fast however big they are: only the rows you can see are drawn, so 50,000 rows filter in about 20 ms. Click a column header to sort, type in the filter box to narrow rows (`/` jumps to it), and click a row (or press Enter on it) to open a drawer with every column in full, the real datasource id, and a button that copies the row as JSON. Each column has an options menu (the `...` button, or Alt+Down on a header) to sort, filter just that column, pin it to the left, hide it, change its width or copy its values; the **Columns** button brings hidden ones back, and **Compact rows** fits more on screen. Datasources show their caption instead of Tableau's internal id (hover for the id). Columns that name things for Tableau rather than for people (`datasource`, `tableau_internal_name`, `connection_id`, `connection`, `zone_id`, and the raw `name` where a caption or current name is shown) come last in every table, in the CLI and in CSV exports too. The overview opens with a sentence about the workbook, its tiles, a **Worth a look** list (relationships that point at nothing, calculations that name fields the workbook does not have, calculations and fields no worksheet uses; each has a Show button that opens that table already filtered to exactly those rows) and what is on each dashboard. The graph view draws joins and relationships as a picture: drag to pan, scroll or the + and - buttons to zoom, hover or Tab to a table to light up its connections (arrow keys move between tables, Enter tells about one, clicking a line shows its keys), **View as list** for a plain table of the same connections, and **Save as SVG**. A big workbook is drawn one connected group at a time. The DOT text is still there, collapsed under the picture, and **Export DOT** downloads it. The Field renames view has the buttons for the feature above: pick a style, datasource and optional reference workbook, then **Create fixed workbook** saves `<name>_renamed` beside the original (and says so if that file already exists) or **Download fixed workbook** sends it to your browser without saving anything. Everything else exports as CSV. It has a dark theme and works in a narrow window.

![py-tbparse GUI, Field renames view with suggested clean names](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/gui-field-renames.png)

![py-tbparse GUI, the relationship graph with one table and its connections highlighted](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/gui-graph.png)

![py-tbparse GUI, the Harbor dark theme with the theme menu open](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/gui-themes.png)

The screenshots are of a made-up demo workbook (`docs/demo/coffee-shop.twb`, built by `scripts/make_demo_workbook.py`); `scripts/readme_screenshots.py` retakes them.

It has no login, so run it on your own machine only. To share it, see [Running as a server](deployment.md) and the Limits section of the [README](https://github.com/DDSNA/py-tbparse/blob/main/README.md#limits).

## Templates

The **Templates** button in the top bar opens a view for filling a template with new data. It works with no workbook open, and **Back to workbook** (or **Back to start**) takes you out again. The address `#templates` opens it directly. The view has three steps, one card each:

1. **Template.** Drop a `.twbx` made with `py-tbparse template make`, press **Choose template...**, or (on your own computer) type its path and press Open. The card then shows the template's name, revision, description, how many required fields, parameters and tokens it has, and what the template check found, problems first. It lists the first 50 findings, **Show more** adds 50 at a time up to 500, and `py-tbparse template check` gives the whole list. A template with several data sources asks which one gets the new data.
2. **New data.** Drop or choose a `.csv`, `.tsv`, `.txt`, an Excel file (`.xlsx`, `.xlsm`; with several sheets you pick one) or a Tableau `.twb`, `.twbx` or `.tds` (with several data sources you pick one). The card shows the kind and the number of columns, with the column names (the first 200) behind **Show the columns**. For a text or Excel file there is an optional field, **Where will this file be on your computer?**: the workbook remembers where its data file is, so type the folder (or the full path) where the file will live. Left empty, the workbook only knows the file name and Tableau asks where the file is when you open it. Database target files (`.json`) are not supported here yet.
3. **Review and create.** This card unlocks when the first two are done. Matching the template's fields to your columns and creating the workbook are not built yet: today it only shows which template and data you chose.

Later steps stay locked, with a one-line reason, until the earlier ones are done. **Change** on a card lets you pick another file. A file dropped on the page goes to the card it lands on, or else to the first empty step (a `.twbx` is the template when none is chosen yet), and the drop overlay says which. Your choices are kept on the server for your session, so a reload brings them back. Files are limited to 200 MB each.

In a shared server ([Running as a server](deployment.md)) there are no path boxes: only dropped or chosen files work, and every visitor has their own choices, deleted when their session ends.
