# py-tbparse

[![PyPI](https://img.shields.io/pypi/v/py-tbparse)](https://pypi.org/project/py-tbparse/)
[![Python](https://img.shields.io/pypi/pyversions/py-tbparse)](https://pypi.org/project/py-tbparse/)
[![CI](https://github.com/DDSNA/py-tbparse/actions/workflows/ci.yml/badge.svg)](https://github.com/DDSNA/py-tbparse/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/DDSNA/py-tbparse/blob/main/LICENSE)

py-tbparse reads Tableau workbooks (`.twb` and `.twbx`) without Tableau. It shows what is inside a workbook, checks it for problems, and makes new copies of it: with cleaner field names, without private details, with only some dashboards, with sheets or calculations from another workbook, or filled with new data from a template. Your original file is never changed.

You can use it in a page in your web browser (no programming), from the command line, or from Python. Tableau and R are not needed. It began as a port of PrigasG's R package [twbparser](https://github.com/PrigasG/twbparser).

![The overview report card for a small demo workbook](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/gui-overview.png)

## Contents

- [User's guide](#users-guide), for people who work with Tableau but do not program
  - [Before you start](#before-you-start): words used here, install, first run, a tour of the screens
  - [I want to...](#i-want-to)
    - [see what is in a workbook](#see-what-is-in-a-workbook)
    - [rename fields safely](#rename-fields-safely)
    - [check a workbook for problems](#check-a-workbook-for-problems)
    - [share a workbook without private data](#share-a-workbook-without-private-data)
    - [keep only some dashboards](#keep-only-some-dashboards)
    - [copy sheets or dashboards between workbooks](#copy-sheets-or-dashboards-between-workbooks)
    - [reuse calculated fields](#reuse-calculated-fields)
    - [reuse colour palettes](#reuse-colour-palettes)
    - [clean out unused things](#clean-out-unused-things)
    - [apply a template](#apply-a-template)
  - [Staying safe and private](#staying-safe-and-private)
  - [Not yet verified in Tableau Desktop](#not-yet-verified-in-tableau-desktop)
  - [Troubleshooting](#troubleshooting)
  - [Glossary](#glossary)
- [For developers and power users](#for-developers-and-power-users): everything it does, Python, the command line, all the guides, development
- [Limits](#limits)
- [Contributing](#contributing), [Credit](#credit), [License](#license)

## User's guide

This guide is for people who build or look after Tableau workbooks and do not write code. It starts with the app in your web browser. Each task also shows the same thing as commands you can copy and paste, for people who want them.

Click a line that starts with a small triangle to open it. Every section opens on its own, so you can jump straight to the task you need.

**The example in this guide.** All the pictures and commands use one public workbook: `Brushing_Superstore_Sales_Map.twb` from [github.com/1230harry/TeamOne_MSc_Group_Project](https://github.com/1230harry/TeamOne_MSc_Group_Project) (MIT licence), built on Tableau's "Sample - Superstore" data. It has one dashboard, four worksheets, three tables (Orders, People, Returns), seven calculated fields and four parameters. We first ran it through py-tbparse's own [share-safe copy](#share-a-workbook-without-private-data) to take out a local file path, and saved the result as `superstore-sales-map.twb`. The pictures were taken with version 0.5.4.

### Before you start

<details>
<summary><b>Words used here</b>: workbook, .twb, .twbx, datasource, field, calculated field, parameter, worksheet, dashboard</summary>

- **Workbook**: the file you save from Tableau Desktop. It holds your sheets, dashboards, calculations and the description of where the data is.
- **`.twb`**: a workbook on its own. It does not contain the data, only where to find it.
- **`.twbx`**: a *packaged* workbook. It is a `.twb` plus, often, the data files, extracts and images, zipped into one file.
- **Datasource**: a connection in the workbook to some data: an Excel file, a CSV file, a database table, or a published Tableau data source. One workbook can have several.
- **Field**: one column of a datasource, such as `Sales` or `Region`. In Tableau you see fields in the Data pane.
- **Calculated field** (or *calculation*): a field you made with a formula, such as `SUM([Profit])/SUM([Sales])`.
- **Parameter**: a value the person viewing the workbook can change, such as "Top N = 10".
- **Worksheet** (or *sheet*): one chart or table.
- **Dashboard**: a page that shows several worksheets together, often with filters.
- **Extract**: a copy of the data that Tableau keeps in a `.hyper` (or older `.tde`) file.

More words (dry run, template, library, palette and so on) are in the [Glossary](#glossary) at the end.

</details>

<details>
<summary><b>Install it</b> (once, about five minutes)</summary>

py-tbparse is a free Python program. You install Python once, then py-tbparse.

1. **Install Python** (version 3.9 or newer) from [python.org/downloads](https://www.python.org/downloads/). On Windows, tick **Add python.exe to PATH** on the first screen of the installer.
2. **Open a terminal.** This is a window where you type commands.
   - Windows: press the Start button, type `cmd` and open **Command Prompt** (or open **Terminal**).
   - macOS: open **Terminal** (in Applications, Utilities).
3. **Install py-tbparse.** Copy this line into the terminal and press Enter:

   ```bash
   python -m pip install py-tbparse
   ```

   On Windows, if `python` is not found, use `py -m pip install py-tbparse`. On macOS, if it is not found, use `python3 -m pip install py-tbparse`.
4. For Excel files as new data for a template, also install the Excel add-on: `python -m pip install "py-tbparse[excel]"`.

To update later: `python -m pip install --upgrade py-tbparse`. To see which version you have: `python -m pip show py-tbparse`.

This installs two commands: `py-tbparse-gui` (the app in your browser) and `py-tbparse` (the command line). Nothing else is installed on your computer, and there is no account to create.

</details>

<details>
<summary><b>First run</b>: start the app and open a workbook</summary>

1. In the terminal, type `py-tbparse-gui` and press Enter. The terminal says `py-tbparse GUI running at http://127.0.0.1:...` and your web browser opens a new tab with the app.
2. Leave the terminal window open while you work. To stop the app, go back to the terminal and press **Ctrl+C**, or close the window.
3. Open a workbook in one of three ways:
   - drag a `.twb` or `.twbx` file from your folder onto the page;
   - press **Open file...** and choose it;
   - paste the full path of the file into the box at the top and press **Load**. Paste the path without quotation marks (Windows' **Copy as path** adds them; delete them).

![The start screen: a box for the path, Load, Open file..., Templates and Theme, and the text "Let's open a workbook"](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/guide-start.png)

You can also open a workbook straight away: `py-tbparse-gui "C:\Users\you\Documents\Tableau\superstore-sales-map.twb"`.

**Opened by path or dropped on the page?** It matters in one place. When you open a workbook by its path, the Field renames screen can save the renamed copy in the same folder as the original. When you drop or choose a file, the app works on a private temporary copy, so it offers a download instead. Every other screen gives you a download either way; the file goes to your browser's usual downloads folder.

The start screen also lists the workbooks you opened by path recently. Your browser keeps that list on this computer.

</details>

<details>
<summary><b>A tour of the screens</b></summary>

After a workbook is open, the list on the left has every screen. The number beside a name is how many rows that table has. The **Workbook** group holds the tools (Overview, Audit, Libraries, Styles, Slice and copy); **Data**, **Data model**, **Dashboards** and **SQL** hold tables you can read and export. **Templates** and **Theme** are buttons at the top.

<details>
<summary>Overview</summary>

The first screen. One sentence about the workbook, a tile for each count, a **Worth a look** list, and what is on each dashboard. Each item in Worth a look has a **Show** button that opens the table with exactly those rows. Click a tile to open its table.

![Overview of superstore-sales-map.twb: 3 datasources, 4 parameters, 2 relationships, 7 calculated fields, 48 raw fields, 1 dashboard; Worth a look lists 4 calculations no worksheet uses and 20 fields no worksheet uses](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/guide-overview.png)

</details>

<details>
<summary>Tables: Fields, Calculated fields, Parameters, Datasources and the rest</summary>

Every table works the same way. Click a column name to sort. Type in **Filter rows** to narrow the rows (press `/` to jump there). Click a row to see every column of it in full. The `...` beside a column name sorts, filters, pins, hides or widens that column. **Columns** brings back hidden columns, **Compact rows** fits more on the screen, and **Export CSV** saves the table for Excel.

Useful tables: **Fields** (every column of every datasource), **Calculated fields** (with their formulas), **Field usage** (which sheets, dashboards and calculations use each field), **Missing references** (calculations that name a field the workbook does not have), **Datasources**, **Parameters**, **Relationships**, **Dashboards** and **Dashboard sheets**.

![The Fields table: 48 rows with caption, datatype, role and table columns](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/guide-fields.png)

</details>

<details>
<summary>Dashboards</summary>

One row per dashboard: how many worksheets it shows and which, its size, and how many filters, parameter controls and actions it has.

![The Dashboards table: Dashboard 1 shows 4 worksheets (Sheet 1 to Sheet 4), size automatic, 2 filters](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/guide-dashboards.png)

</details>

<details>
<summary>Relationship graph</summary>

The tables of the data model and how they connect, as a picture. Drag to move it, scroll or use **+** and **-** to zoom, and point at a table to see its connections and their keys. **View as list** shows the same as a table; **Save as SVG** saves the picture.

![The relationship graph: Orders connects to People on Region = Region (People) and to Returns on Order ID = Order ID (Returns)](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/guide-graph.png)

</details>

<details>
<summary>Field renames, Audit, Libraries, Styles, Slice and copy, Templates</summary>

These are the tools. Each one has its own task below, with a picture:

- Field renames: [rename fields safely](#rename-fields-safely)
- Audit: [check a workbook for problems](#check-a-workbook-for-problems)
- Slice and copy: [keep only some dashboards](#keep-only-some-dashboards) and [copy sheets between workbooks](#copy-sheets-or-dashboards-between-workbooks)
- Libraries: [reuse calculated fields](#reuse-calculated-fields)
- Styles: [reuse colour palettes](#reuse-colour-palettes)
- Templates: [apply a template](#apply-a-template)

</details>

<details>
<summary>Theme and dark mode</summary>

**Theme** at the top right changes the colours (34 themes) and switches between Light, Dark and **Auto (follow my system)**.

![The Calculated fields table in dark mode, with the formula of each calculation](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/guide-dark.png)

</details>

</details>

<details>
<summary><b>Using the commands</b> (optional): how to run the copy-paste lines in this guide</summary>

Every task below has a "Same thing with commands" part. You type these into the terminal from [Install it](#before-you-start).

- Go to the folder that holds your workbook first, so you can use its plain file name: `cd "C:\Users\you\Documents\Tableau"` (Windows) or `cd ~/Documents/Tableau` (macOS). Or type the full path of the file each time.
- Put a name in double quotes when it has spaces: `--dashboards "Dashboard 1"`.
- A command that would change something first shows a plan and writes nothing. You add `--write` when the plan looks right. The task says when a command works differently.
- `py-tbparse --help` lists the basic options; `py-tbparse audit --help` (and so on for each command) explains one command.

</details>

### I want to...

#### See what is in a workbook

It lists everything in a workbook: datasources, fields, calculations with their formulas, parameters, relationships, dashboards and which sheets use which field. It only reads the file.

<details>
<summary>Steps, what you will see, and the commands</summary>

**In the app**

1. Start the app and open the workbook ([First run](#before-you-start)).
2. Read the **Overview**: the counts, the **Worth a look** list and the dashboards.
3. Click a table on the left, for example **Calculated fields** to see every formula, or **Field usage** to see where a field is used.
4. To keep a table, press **Export CSV** and open the file in Excel.
5. For a full written description of the workbook, open **Audit** and press **Data dictionary (Markdown)**. You get a text page with every datasource, field, formula, parameter, worksheet and dashboard.

**What you will see.** For the example: "superstore-sales-map.twb has 1 dashboard, 4 worksheets and 3 datasources", with tiles for 4 parameters, 2 relationships and 7 calculated fields. See the [Overview picture](#before-you-start) in the tour.

**What it will not do.** It does not show your data (only its description), does not draw your charts, and does not change the workbook.

<details>
<summary>Same thing with commands</summary>

```bash
py-tbparse superstore-sales-map.twb                       # the counts
py-tbparse superstore-sales-map.twb tables                # the names of all tables
py-tbparse superstore-sales-map.twb calculated-fields     # every calculation and its formula
py-tbparse superstore-sales-map.twb fields --format csv -o fields.csv    # a table as a CSV file
py-tbparse docs superstore-sales-map.twb -o superstore-sales-map.md      # the data dictionary page
```

Other tables: `datasources`, `parameters`, `field-usage`, `missing-references`, `relationships`, `dashboards`, `dashboard-sheets`, `custom-sql`. The data dictionary is explained in [docs/audit.md](https://github.com/DDSNA/py-tbparse/blob/main/docs/audit.md#data-dictionary).

</details>

**Good to know.** The data dictionary prints formulas and captions as the workbook has them. If someone typed a password or a folder into a formula, it will be on the page, so read it before you share it.

</details>

#### Rename fields safely

It suggests tidy names (`SalesLOD` becomes `Sales LOD`) and writes a new copy of the workbook with them. Your sheets and formulas keep working, because only the name people see (the caption) changes.

<details>
<summary>Steps, what you will see, and the commands</summary>

**In the app**

1. Open the workbook and click **Field renames** (in the Data group).
2. Pick a style (**Title Case** is the default), a datasource or **(all datasources)**, and **Fields only** or everything in the workbook (sheets, dashboards, datasources, parameters, folders too).
3. Optional: type the path of an older workbook in **Reference workbook path**. Fields that match take that workbook's spelling. This helps after switching a workbook to a new datasource.
4. Untick any rename you do not want. **Select all** and **Select none** act on the whole list.
5. Press **Create with N of N renames** (saves `<name>_renamed.twb` next to the original; only when you opened the workbook by its path) or **Download fixed workbook**.

**What you will see.** For the example, three suggestions: `Sub-Category` to `Sub Category`, `SalesLOD` to `Sales LOD`, `SalesLOD%` to `Sales LOD%`.

![Field renames: Title Case, all datasources, Fields only; three ticked suggestions and the button Create with 3 of 3 renames](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/guide-renames.png)

**What it will not do.** It does not change the internal names that formulas use, does not edit the suggested names on screen (use the CSV route below for that), and does not reconnect a datasource for you. Sheets that already point at a missing field stay broken.

**Staying safe.** The original is not changed. The copy is a new file; if it already exists, the app says so and does not replace it. To undo, delete the copy.

<details>
<summary>Same thing with commands</summary>

```bash
py-tbparse rename superstore-sales-map.twb --only-changed          # show the suggestions; writes nothing
py-tbparse rename superstore-sales-map.twb --all --only-changed    # also sheets, dashboards, datasources...
py-tbparse rename superstore-sales-map.twb --write-workbook        # writes superstore-sales-map_renamed.twb
```

To choose the names yourself: save the suggestions with `py-tbparse rename superstore-sales-map.twb -f csv -o mapping.csv`, change the `suggested` column in Excel (leave a cell empty to keep that name), save as CSV, then `py-tbparse rename superstore-sales-map.twb --apply mapping.csv`. More in [docs/renaming.md](https://github.com/DDSNA/py-tbparse/blob/main/docs/renaming.md).

</details>

<details>
<summary>Common messages</summary>

- `error: refusing to overwrite existing file: superstore-sales-map_renamed.twb`: a renamed copy is already there. Move or rename it, or pick another name with `--write-workbook NEW_NAME.twb`.
- `reason` = `already clean`: nothing to change for that field. `conflict`: two fields would get the same name, so that one keeps its name.

</details>

</details>

#### Check a workbook for problems

It lists what the author probably did not mean: calculations nobody uses, two calculations with the same formula, formulas that name a field that does not exist, calculations that refer to each other in a circle, unused parameters, worksheets on no dashboard, custom SQL, and data files that only exist on one computer.

<details>
<summary>Steps, what you will see, and the commands</summary>

**In the app**

1. Open the workbook and click **Audit**.
2. Read the summary line and the findings. Each finding has a rule (A001 to A011), a severity (Error, Warning or Info), a message with a suggested fix, and the object it is about.
3. Narrow the list with the severity and rule menus or the search box.
4. **Skip rules** turns a rule off, for example A008 if you know the workbook only runs on your computer.
5. **Download CSV** or **Download JSON** saves every finding.

**What you will see.** For the example: "5 info". Three calculations no worksheet uses (Category LOD, Profit (bin), Profit Ratio) and two parameters only those use.

![Audit: 5 info findings, rules A001 and A005, each with a message, a fix and the object](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/guide-audit.png)

**What it will not do.** It does not change anything, does not give a score, and does not open the workbook in Tableau. "Unused" means unused in this workbook: another workbook or a published data source might still use the field. To remove what it finds, see [clean out unused things](#clean-out-unused-things).

<details>
<summary>Same thing with commands</summary>

```bash
py-tbparse audit superstore-sales-map.twb                              # a table of findings
py-tbparse audit superstore-sales-map.twb --format csv -o findings.csv # save them for Excel
py-tbparse audit superstore-sales-map.twb --skip A008                  # leave one rule out
```

The rules are listed by `py-tbparse audit --help` and explained in [docs/audit.md](https://github.com/DDSNA/py-tbparse/blob/main/docs/audit.md#rules).

</details>

<details>
<summary>Common messages</summary>

- `Exit code 0: no error finding` (in the app) or a count such as `5 info` (in the terminal): the check ran. Info findings are hints, not errors.
- A003 `error`: a calculation names a field the workbook does not have. In Tableau that calculation shows as broken.
- A008: the workbook points at a file by a full path on one computer (such as `C:\Users\...`). It works only where that file exists. It is very common.

</details>

</details>

#### Share a workbook without private data

It writes a copy that is safer to post in a forum or send to a vendor: user names, passwords, server, database and schema names, folders, custom SQL, extracts and packed data files, comments, user filters, author ids and thumbnails are taken out.

<details>
<summary>Steps, what you will see, and the commands</summary>

This is a command-line tool only; the app does not have a screen for it.

1. Open a terminal in the workbook's folder ([Using the commands](#before-you-start)).
2. Run:

   ```bash
   py-tbparse sanitize superstore-sales-map.twb superstore-sales-map.shared.twb --report
   ```

   The first name is your workbook, the second the new file. A `.twb` gives a `.twb`, a `.twbx` gives a `.twbx`.
3. Read the report. It lists how much it removed of each kind and the **leftovers** it could not judge.
4. Open the new file in Tableau and look at it before you share it.

**What you will see.** For the original example workbook it removed 10 items (a server entry, a folder path, an extract, a comment, the repository location and 5 thumbnails) and listed 2 leftovers: table names it keeps, and titles, captions, formulas and text it does not read.

**What it will not do.** It is a clean-up, not a guarantee. It does not read titles, captions, field names, formulas or text boxes for personal or company information, and it keeps table names, because sheets need them. A calculation that uses `USERNAME()` is kept and listed. Without the data, Tableau shows the sheets but cannot draw them until you connect to data again.

**Staying safe.** This command writes the new file straight away (there is no plan step), but it never writes over your workbook and refuses a file that already exists unless you add `--overwrite`. Running it again on its own output removes nothing more.

<details>
<summary>More options</summary>

- `--placeholders` writes stand-in values (`server.example.com`, `database`, `schema`, `user`) instead of empty ones.
- `--keep comments` leaves one kind alone (the kinds are listed by `py-tbparse sanitize --help`).
- `--fake-data` (experimental) adds a small made-up CSV for each simple datasource and connects to it, so the sheets can draw. The values are invented, never taken from your data. The output is a `.twbx`.

Details in [docs/sanitize.md](https://github.com/DDSNA/py-tbparse/blob/main/docs/sanitize.md).

</details>

<details>
<summary>Common messages</summary>

- `wrote superstore-sales-map.shared.twb: 10 item(s) removed, 2 leftover(s) listed (use --report to see them)`: done; add `--report` to see the list.
- `error: refusing to overwrite the input workbook`: the two names are the same. Give the new file another name.
- `error: refusing to overwrite existing file`: a file with the new name is already there.

</details>

</details>

#### Keep only some dashboards

It makes a smaller copy of a workbook with only the dashboards you pick. The other dashboards go, the worksheets only they used go, and then the calculations, parameters and datasources nothing uses any more.

<details>
<summary>Steps, what you will see, and the commands</summary>

**In the app**

1. Open the workbook and click **Slice and copy**.
2. In **Slice: keep some dashboards**, tick the dashboards to keep.
3. Read the **Plan**: what is kept, what is removed, actions that cannot stay, and what was removed as unused afterwards.
4. Leave **Remove unused calculations, parameters and datasources afterwards** on to clean up, or untick it to keep them. Tick **Stop instead of dropping actions** if you would rather be told than lose an action.
5. Press **Download sliced workbook**. You get `<name>_sliced.twb` (or `.twbx`).

**What you will see.** The example has only one dashboard, so keeping it keeps all four worksheets, and the clean-up removes 3 calculations and 1 parameter that nothing used.

![Slice plan: keep 1 dashboard and 4 worksheets, remove 0; then removed as unused: 3 calculations, 1 parameter, 0 datasources; the Download sliced workbook button](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/guide-slice.png)

**What it will not do.** It does not change the open workbook. It does not remove extracts, images or thumbnails from inside a `.twbx`. The clean-up also removes calculations that were already unused before; untick the box if you want to keep them.

<details>
<summary>Same thing with commands</summary>

```bash
py-tbparse slice superstore-sales-map.twb --dashboards "Dashboard 1"                                 # the plan; writes nothing
py-tbparse slice superstore-sales-map.twb --dashboards "Dashboard 1" --write -o superstore-sliced.twb # write the new file
```

Several dashboards: `--dashboards "Overview,KPIs"`. `--strict` stops instead of dropping actions; `--no-prune` skips the clean-up. More in [docs/slice.md](https://github.com/DDSNA/py-tbparse/blob/main/docs/slice.md).

</details>

<details>
<summary>Common messages</summary>

- `dry run: nothing was written (use --write -o OUT)`: the plan only. Add `--write -o NEW_NAME.twb`.
- `error: unknown dashboard(s): 'Overview'; valid dashboards: 'Dashboard 1'`: check the spelling; the message lists the real names.
- A selection that shows no worksheet is refused: a workbook needs at least one worksheet.

</details>

</details>

#### Copy sheets or dashboards between workbooks

It copies worksheets (in the app or with a command) or whole dashboards (command only) from one workbook into a new copy of another. The calculations and parameters they need come along.

<details>
<summary>Steps, what you will see, and the commands</summary>

**Before you start.** Both workbooks must use the same datasource: the same connection and the same internal name in Tableau. In practice that means workbooks that started from the same file, for example a copy of a workbook that went its own way. If the target has no such datasource, the sheet is refused with the reason.

**In the app** (worksheets)

1. Open the workbook you copy **from**, click **Slice and copy**, and go to **Copy sheets into another workbook**.
2. Press **Choose the target workbook** and pick the workbook to copy **into**. It is not changed; you get a new copy of it.
3. Tick the worksheets to copy.
4. Choose what happens when a name is already in the target: **Stop** (the default: nothing is made and the clashes are listed), **Rename** (the copy becomes `Name (2)`) or **Skip**.
5. Read the plan: each sheet is **Copy**, **Skipped** or **Refused** with the reason, then what is dropped and which calculations and parameters are added.
6. Press **Download new workbook**. You get `<target>_sheetcopy.twb`.

**What you will see.** Here the target is a second copy of the example, so every name is already there. With **Stop**, the plan says `Stopped: 'Sheet 1' is already a sheet or dashboard of the target` and the download stays off:

![Copy sheets with Stop: Stopped, Sheet 1 is already a sheet or dashboard of the target; Sheet 1 Not copied (stops)](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/guide-copy-stop.png)

With **Rename**, the plan copies `Sheet 1` as `Sheet 1 (2)`, and the calculations it needs are **Already there**:

![Copy sheets with Rename: Plan 1 sheet to copy; Sheet 1 copied as Sheet 1 (2); Subcategory LOD and SalesLOD already there](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/guide-copy-rename.png)

**What it will not do.** It does not copy a sheet that mixes two datasources (a blend), does not add a datasource the target lacks, does not copy thumbnails or images, and drops action filters (listed in the plan). In the app it copies worksheets only; dashboards are copied with the command below.

<details>
<summary>Same thing with commands</summary>

```bash
py-tbparse sheet copy superstore-sales-map.twb --sheets "Sheet 1" --to other.twb                     # the plan; writes nothing
py-tbparse sheet copy superstore-sales-map.twb --sheets "Sheet 1" --to other.twb --on-clash rename --write
py-tbparse dashboard copy superstore-sales-map.twb --dashboards "Dashboard 1" --to other.twb         # whole dashboards, the plan
py-tbparse dashboard copy superstore-sales-map.twb --dashboards "Dashboard 1" --to other.twb --on-clash rename --write
```

With `--write` the new file is `other_sheetcopy.twb` or `other_dashcopy.twb`, or the name you give with `-o`. Dashboard copy also brings the dashboard's filters and the actions that stay inside the copied set; other actions are dropped and listed. More in [docs/sheet-copy.md](https://github.com/DDSNA/py-tbparse/blob/main/docs/sheet-copy.md) and [docs/dashboard-copy.md](https://github.com/DDSNA/py-tbparse/blob/main/docs/dashboard-copy.md).

</details>

<details>
<summary>Common messages</summary>

- `plan only, nothing written; add --write to make the workbook`: the plan only.
- `error: 'Sheet 1' is already a sheet or dashboard of the target (on_clash='fail')`: choose `--on-clash rename` or `skip` (Rename or Skip in the app).
- `refused ... the target has no datasource with the connection of 'Sample - Superstore'` and `error: no sheet can be copied`: the target does not use the same datasource. See "Before you start" above.

</details>

</details>

#### Reuse calculated fields

It saves calculated fields and parameters from one workbook in a small *library* file, and adds them to another workbook, so you do not type your KPIs again.

<details>
<summary>Steps, what you will see, and the commands</summary>

**In the app**

1. Open the workbook that has the calculations and click **Libraries**.
2. In **Export from this workbook**, tick the calculations and parameters you want. By default the ones they use come along too.
3. Press **Export library file**. You get a `*.library.json` file.
4. Open the workbook you want to add them to, click **Libraries**, and in **Add a library to this workbook** press **Choose a library file**.
5. Pick what happens when a field with the same name is already there: **Stop** (default), **Rename** or **Skip**.
6. Read the plan, then press **Download new workbook**. You get `<workbook>_library.twb`.

**What you will see.** For the example, the seven calculations and parameters with their formulas, two of them ticked:

![Libraries: Export from this workbook, 2 selected (Profit Ratio and Category LOD) of 7 calculations and parameters, with their formulas](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/guide-libraries.png)

**What it will not do.** It does not move sets, groups or bins, does not replace a field that already exists, and does not export a calculation that uses another datasource (it says which). The target needs fields that match the ones the calculations use (`Sales`, `Profit`...), by the same or a close name.

<details>
<summary>Same thing with commands</summary>

```bash
py-tbparse library export superstore-sales-map.twb -o kpis.library.json --field "Profit Ratio" --field "Category LOD"
py-tbparse library show kpis.library.json                  # what is inside, with the formulas
py-tbparse library import other.twb kpis.library.json      # the plan; writes nothing
py-tbparse library import other.twb kpis.library.json --write   # writes other_library.twb
```

`library export` writes the library file straight away (it never changes the workbook). More in [docs/libraries.md](https://github.com/DDSNA/py-tbparse/blob/main/docs/libraries.md).

</details>

<details>
<summary>Common messages</summary>

- `skip-identical` / "the target has this calculation": it is already there; nothing to add.
- `fail-unmapped` / "the target has no match for [Profit], [Sales]": the target has no field with that name. Pass a mapping CSV (`--mapping`, columns `field` and `mapped_to`).
- `add-renamed`: a different field already has that name, and you chose Rename; the new one gets `(2)`.

</details>

</details>

#### Reuse colour palettes

It copies named colour palettes between workbooks, a `Preferences.tps` file and a small `*.style.json` file, so your team's colours are in Tableau's colour picker.

<details>
<summary>Steps, what you will see, and the commands</summary>

**In the app**

1. Open a workbook and click **Styles**.
2. **Palettes in this workbook** lists its custom palettes with their colours. Tick some and press **Export style file** or **Export as Preferences.tps**.
3. To add palettes to the open workbook: in **Add palettes from a file**, press **Choose a palette file** (a `*.style.json` or a `Preferences.tps`).
4. Pick what happens when a palette with the same name and other colours is already there: **Stop** (default), **Skip**, **Rename** or **Replace**.
5. Read the plan and press **Download new workbook** (`<workbook>_palettes.twb`).

**What you will see.** The example workbook has no custom palettes. After choosing a small palette file with two palettes, the plan says **2 to add**:

![Styles: Add palettes from a file, brand-palettes.tps with 2 palettes, the four clash choices, and the plan 2 to add with the colour chips of Superstore Brand](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/guide-styles.png)

**What it will not do.** It only adds palettes to the colour picker. **It recolours nothing**: every chart keeps its colours. It does not move fonts, borders or other formatting.

**Staying safe.** It never writes over your workbook or over a file called `Preferences.tps`. For Tableau Desktop to offer a palette from a `.tps` file, you copy the new file over your own `Preferences.tps` in `My Tableau Repository` yourself (keep a backup of the old one) and restart Tableau.

<details>
<summary>Same thing with commands</summary>

```bash
py-tbparse style show brand-palettes.tps                                  # the palettes in a file
py-tbparse style import brand-palettes.tps superstore-sales-map.twb       # the plan; writes nothing
py-tbparse style import brand-palettes.tps superstore-sales-map.twb --write   # writes superstore-sales-map_palettes.twb
py-tbparse style export superstore-sales-map_palettes.twb -o brand.style.json
```

More in [docs/styles.md](https://github.com/DDSNA/py-tbparse/blob/main/docs/styles.md).

</details>

<details>
<summary>Common messages</summary>

- `palettes are now in the colour picker; existing marks keep their colours`: done.
- `plan only, nothing written; add --write to write a new file`: the plan only.
- A name clash with **Stop** (`--on-clash fail`): nothing is written; choose Skip, Rename or Replace.
- `invalid`: a palette without a name, colours or a known type. It is left out; the rest is written.

</details>

</details>

#### Clean out unused things

It removes calculated fields and parameters that nothing uses, and on request worksheets that are on no dashboard and datasources nothing uses, into a new copy. It removes something only when nothing that stays refers to it.

<details>
<summary>Steps, what you will see, and the commands</summary>

This is a command-line tool. In the app, the [audit](#check-a-workbook-for-problems) shows what is unused, and [Slice and copy](#keep-only-some-dashboards) can clean up after keeping some dashboards.

1. See the plan:

   ```bash
   py-tbparse prune superstore-sales-map.twb
   ```

2. Read it. Each line says **would remove** or **kept**, and why.
3. When it looks right, write a new file:

   ```bash
   py-tbparse prune superstore-sales-map.twb --write -o superstore-pruned.twb
   ```

**What you will see.** For the example:

```text
would remove  calculation Sample - Superstore: Profit Ratio
would remove  calculation Sample - Superstore: Category LOD
would remove  calculation Sample - Superstore: Profit (bin)
would remove  parameter   Parameters: Profit Bin Size
kept         parameter   Parameters: Top Customers
            why: still named by <groupfilter> in group [Top Customers by Profit]

would remove: 3 calculation(s), 1 parameter(s), 0 sheet(s); kept 1 finding(s) that something still uses
dry run: nothing was written (use --write -o OUT)
```

(The real output also has a `why:` line under each item.)

**What it will not do.** It does not see other workbooks or published data sources that may use a field. It does not remove worksheets unless you add `--sheets`, or datasources unless you add `--datasources`. It does not shrink extracts inside a `.twbx`.

**Staying safe.** Without `--write` nothing is written. With it, a new file is written; your workbook is never changed, and an existing file is refused unless you add `--overwrite`.

<details>
<summary>Common messages</summary>

- `error: refusing to overwrite existing file: superstore-pruned.twb (use --overwrite)`: pick another name.
- `-o OUT is only used with --write (without it prune is a dry run)`: add `--write`.
- `kept ... still named by ...`: something still uses it, so it stays. More in [docs/prune.md](https://github.com/DDSNA/py-tbparse/blob/main/docs/prune.md).

</details>

</details>

#### Apply a template

A template is a workbook prepared for reuse. You fill it with new data (a CSV or Excel file, another workbook, or a database table) and get a new workbook with the same sheets, dashboards and calculations.

<details>
<summary>Steps, what you will see, and the commands</summary>

**Make a template (in the app)**

1. Open the finished workbook, then press **Templates** at the top.
2. Scroll to **Make a template from your open workbook**. Give it a name and, if you like, a line about what it is for.
3. Press **Make template**. It shows how many fields the template needs and what the template check found. Press **Download the template** to keep it (a `.template.twbx` file), or **Use it as the template** to fill it right away.

Passwords and user names are removed from the template, and extracts and data files are left out. Server names, custom SQL and formulas are kept as written, so read the template check before you share it.

![Make a template: name Superstore sales map; Made Superstore sales map.template.twbx, 5 required fields, 2 parameters; template check: 3 worth knowing](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/guide-template-make.png)

**Fill a template with new data (in the app)**

1. Press **Templates**. In step **1 Template**, choose the `.template.twbx` (or use the one you just made).
2. In step **2 New data**, choose your new data: a `.csv`, an Excel file, or a Tableau `.twb`, `.twbx` or `.tds`. For a CSV or Excel file, you can type the folder where the file will live on your computer, so Tableau finds it.
3. In step **3 Review and create**, check **Match the fields to your columns**. Each field the template needs gets one of your columns. Fix a **Missing** row by picking a column in its menu.
4. Fill in **Parameters** and **Text to fill in** if the template has any.
5. Read **Check before you create**. **Problems to fix** must be empty.
6. Press **Create workbook**. The new workbook downloads.

**What you will see.** The example template needs 5 fields. A small CSV with the columns `State`, `Region`, `Category`, `Sub_Category`, `Sales Amount`, `Order Date` matches three of them by name; `State/Province` and `Sales` are **Missing** until you pick `State` and `Sales Amount` in their menus:

![Match the fields to your columns: State/Province missing, Region, Category and Sub-Category matched by name, Sales missing](https://raw.githubusercontent.com/DDSNA/py-tbparse/main/docs/guide-template-mapping.png)

**What it will not do.** One CSV or one Excel sheet fills one table. A template whose datasource joins several tables (like the example, with Orders, People and Returns) says so in the check (`the datasource has 3 tables`); use a workbook or `.tds` as the data so its joins come along. It never contacts a database. It does not merge changes you made in Tableau to an earlier output.

**Staying safe.** The template and the data are not changed. In the app the new workbook is a download. A required field without a column blocks **Create** unless you tick **Create anyway**, and then the sheets that use it stay broken. Never type a password as a parameter value: it would be saved inside the new workbook.

<details>
<summary>Same thing with commands</summary>

```bash
py-tbparse template make superstore-sales-map.twb --name "Superstore sales map"      # writes superstore-sales-map.template.twbx
py-tbparse template check superstore-sales-map.template.twbx                         # what to look at before sharing it
py-tbparse template apply superstore-sales-map.template.twbx --data new-sales.csv    # the matching; writes nothing
py-tbparse template apply superstore-sales-map.template.twbx --data new-sales.csv --mapping-out map.csv
#   open map.csv in Excel, fill the mapped_to column for the missing fields (State, Sales Amount), save as CSV
py-tbparse template apply superstore-sales-map.template.twbx --data new-sales.csv --mapping map.csv --write
```

The last line writes `superstore-sales-map_new-sales.twbx` beside the template and prints `wrote ... (6 field(s) mapped, 0 missing, ...)`. Set a parameter with `-p "Top Customers=10"`. Excel data needs the Excel add-on from [Install it](#before-you-start) and `--sheet NAME` when the file has several sheets. One template for a whole folder of files, databases, saved answers and updates are in [docs/templates.md](https://github.com/DDSNA/py-tbparse/blob/main/docs/templates.md).

</details>

<details>
<summary>Common messages</summary>

- `missing: Sales (breaks: Sheet 1; Sheet 3; Sheet 4; dashboards: Dashboard 1; ...)`: no column was found for that field, and these sheets would break.
- `required fields are unmapped; edit the mapping (--mapping-out / --mapping) or pass --allow-missing`: fix the mapping, or write anyway with `--allow-missing`.
- `error: refusing to overwrite existing file`: a workbook with that name is already there.
- `the datasource has 3 tables`: see "What it will not do" above.

</details>

</details>

### Staying safe and private

<details>
<summary>What stays on your computer, and what is never changed</summary>

- **Everything stays on your computer.** The app runs on your own machine at an address only your computer can reach (`127.0.0.1`). It sends nothing to the internet, and the page loads nothing from other websites.
- **Your files are never changed.** Every tool writes a *new* file or a download. None of them writes over the workbook you opened, and they refuse to replace an existing file unless you ask (`--overwrite` on the command line).
- **Look before you write.** In the app, every tool shows its plan before you download anything. On the command line, `prune`, `slice`, `sheet copy`, `dashboard copy`, `library import`, `style import` and `template apply` only print a plan until you add `--write`. Commands that write straight away: `sanitize`, `rename --write-workbook`, `library export`, `style export`, `template make`, and anything with `-o` that saves a report.
- **Dropped files.** A file you drop on the page, or choose with Open file..., is copied to a private temporary folder (up to 200 MB). That copy is deleted when you open another workbook or stop the app.
- **The recent list.** Paths you open by typing them are listed on the start screen. Your web browser keeps that list on this computer.
- **No login.** The app has no password. Run it on your own computer only, not on a shared network. Sharing it with a team needs a server set up by IT (see [Limits](#limits)).
- **Undo** is simple: your original is untouched, so delete the new file and start again. Keep backups of your workbooks anyway, as you would with any tool.

</details>

### Not yet verified in Tableau Desktop

<details>
<summary>Read this before you rely on a file the tool made</summary>

The workbooks this tool writes are checked against Tableau's published file format and for broken references, on 200 real public workbooks. That is not the same as opening them in Tableau. A template filled with a CSV was opened in Tableau once, for one workbook, and drew its sheets. Nothing else in this guide (renamed copies, sliced and pruned copies, copied sheets and dashboards, added libraries and palettes, share-safe copies) has been opened in Tableau Desktop.

So:

1. Keep a backup of your workbook (the tool never changes it, but backups are good practice).
2. Open every new file in Tableau Desktop and look at each sheet and dashboard before you use it or share it.
3. If something looks wrong, tell us at [github.com/DDSNA/py-tbparse/issues](https://github.com/DDSNA/py-tbparse/issues).

The details per feature are in [docs/verify-in-tableau.md](https://github.com/DDSNA/py-tbparse/blob/main/docs/verify-in-tableau.md).

</details>

### Troubleshooting

<details>
<summary>Problems when installing or starting</summary>

- **`python` is not recognised / command not found.** Python is not installed, or not on the PATH. On Windows try `py` instead of `python`, or install Python again with **Add python.exe to PATH** ticked. On macOS try `python3`.
- **`py-tbparse-gui` is not recognised / command not found** after installing. The folder pip installs commands into is not on your PATH. Use `python -m py_tbparse.webgui` instead of `py-tbparse-gui`, and `python -m py_tbparse.cli` instead of `py-tbparse` (on Windows, `py -m ...`).
- **The browser does not open.** Copy the address the terminal prints (`http://127.0.0.1:...`) into your browser.
- **The page stops working after I closed the terminal.** The terminal window is the app. Start it again with `py-tbparse-gui`.
- **Excel data is refused.** Install the add-on: `python -m pip install "py-tbparse[excel]"`. Old `.xls` and `.xlsb` files are not read; save them as `.xlsx` first.

</details>

<details>
<summary>Problems when opening a workbook</summary>

- **"... Check the path, or drop the file onto the page instead."** The path in the box is wrong. Remove quotation marks around it, check the spelling, or drag the file onto the page.
- **"that .twbx is damaged or not a zip archive."** The file is not a real packaged workbook. Save it again from Tableau.
- **"there is no workbook (.twb) inside that .twbx."** The `.twbx` has no workbook inside, for example a packaged data source. Use the `.twbx` that Tableau saved as a workbook.
- **Create is missing on Field renames; there is only Download.** You opened the file by dropping or choosing it. That is fine: download the copy. To save next to the original, open it by typing its path instead.
- **The file is larger than 200 MB.** The app takes files up to 200 MB. Use the command line, or a copy without extracts.

</details>

<details>
<summary>Problems with results</summary>

- **A tool says "Stop", "Stopped" or `on_clash='fail'`.** A name is already used in the target. Choose Rename or Skip (`--on-clash rename` or `skip`).
- **A sheet is "Refused".** The plan gives the reason, usually that the target workbook does not have the same datasource.
- **A command printed a plan but no file.** That is the plan step. Add `--write` (and `-o NEW_NAME` where the task shows it).
- **The new workbook looks wrong in Tableau.** Use your original (it is unchanged), and please report it at [github.com/DDSNA/py-tbparse/issues](https://github.com/DDSNA/py-tbparse/issues) with the command or the screen you used.

</details>

### Glossary

<details>
<summary>The words this tool uses</summary>

- **Terminal** (command prompt): a window where you type commands. See [Install it](#before-you-start).
- **Command**: one line you type in the terminal, such as `py-tbparse audit superstore-sales-map.twb`.
- **Path**: where a file is on your computer, such as `C:\Users\you\Documents\Tableau\superstore-sales-map.twb`.
- **Dry run** or **plan**: the tool shows what it would do and writes nothing.
- **Caption**: the name of a field that people see in Tableau. Formulas use a separate internal name, which renaming does not change.
- **Clash**: the target already has something with the same name but a different definition. You choose Stop (fail), Rename or Skip, and for palettes also Replace.
- **Audit** and **finding**: the check of a workbook and one thing it found. Each has a rule id such as A001.
- **Data dictionary**: a written page describing everything in a workbook.
- **Sanitize** (share-safe copy): a copy with private details taken out.
- **Slice**: a copy that keeps only some dashboards.
- **Prune**: a copy with unused calculations, parameters (and, if asked, sheets and datasources) removed.
- **Library**: a small `*.library.json` file holding calculated fields and parameters to add to other workbooks.
- **Palette**: a named list of colours for Tableau's colour picker. **`Preferences.tps`**: the file in `My Tableau Repository` where Tableau Desktop keeps your own palettes.
- **Template**: a `.template.twbx` made from a finished workbook, ready to be filled with new data. **Mapping**: which column of the new data fills which field of the template.
- **Relationship** and **join**: how the tables of a datasource connect.
- **Exit code**: a number a command gives back when it ends (0 means fine). Only matters for automation.

</details>

## For developers and power users

<details>
<summary><b>Everything it does</b> (full feature list)</summary>

- Lists what is in a workbook: datasources, parameters, fields, calculations, joins, relationships, dashboards, custom SQL, published sources.
- Checks relationships and finds calculations that refer to fields the workbook does not have.
- Shows which worksheets, dashboards and calculations use each field.
- Suggests clean names for fields, sheets, dashboards and other objects, and writes a renamed copy.
- Turns a finished workbook into a template you can fill with other data: a CSV, an Excel sheet (`.xlsx`, `.xlsm`), another workbook, or a database table described in a target file. The database is never contacted. Supported: MySQL, PostgreSQL, SQL Server and Snowflake.
- Fills `{{token}}` placeholders in titles, text and captions, so one template gives each customer its own dashboard.
- Makes one workbook per file in a folder (`template apply-folder`), brings a workbook up to a newer template revision (`template update`) and lints a template (`template check`).
- Checks a folder or glob of monthly CSV/Excel files against a template or saved answers (`template drift`): missing, renamed and extra columns, type conflicts, encoding, separator, moved Excel headers, empty files, with fingerprints per file. It does not write a union workbook yet.
- Audits a workbook (`audit`: unused or duplicate calculations, missing references, custom SQL, absolute-path leftovers) and writes a Markdown data dictionary of it (`docs`). Read-only; never opened in Tableau.
- Writes a share-safe copy of a workbook (`sanitize IN OUT --report`): user names, servers, databases, paths, custom SQL, extracts, comments and thumbnails out, a report of what was removed and what it could not judge, optional placeholders and synthetic data. A clean-up, not a guarantee.
- Removes what the audit finds unused (`prune WORKBOOK`: unused calculations and parameters, worksheets on no dashboard only with `--sheets`), only if nothing that stays refers to it. A dry run by default; `--write -o OUT` writes a new file.
- Keeps selected dashboards of a workbook and drops the rest (`slice WORKBOOK --dashboards A,B --write -o OUT`): the other dashboards, the worksheets no kept dashboard uses, their windows, and then the calculations, parameters and datasources only they used. Actions that depend on removed sheets are dropped and reported (`--strict` refuses instead). Not opened in Tableau. Also a Slice and copy view in the GUI.
- Copies worksheets from one workbook into another (`sheet copy SRC --sheets A,B --to TARGET --write -o OUT`): the target needs a datasource with the same connection and the same internal name; the calculations and parameters the sheets need are added, action filters are dropped and listed, and a clash fails unless you pick `--on-clash rename` or `skip`. A dry run by default; the same in the GUI's Slice and copy view, which shows the plan and ends in a download.
- Copies dashboards, with all their sheets, from one workbook into another (`dashboard copy SRC --dashboards A,B --to TARGET --write -o OUT`): the rules of sheet copy, plus the dashboard's own datasources and filter, parameter and legend dependencies, a new dashboard window, and the actions whose source and targets are all copied (the others are dropped and listed). One sheet that cannot be copied refuses its dashboard. A dry run by default.
- Writes the findings of `validate`, `audit` and `template check` as JUnit, SARIF or GitHub annotations for CI (`--format junit|sarif|github`), with a pre-commit hook and a sample workflow.
- Takes calculated fields and parameters out of one workbook into a library file and adds them to another (`library export`, `library import`). The output follows what Tableau writes but has not been opened in Tableau.
- Saves the layout of a dashboard (containers, text, styles, one slot per sheet) as a scaffold and makes a new dashboard from it with your own sheets (`scaffold make`, `show`, `apply`). First slice: a single tiled root only; filters, legends, controls, images and device layouts are dropped and listed. It has not been opened in Tableau.
- Takes named colour palettes out of workbooks and `Preferences.tps` files and writes them into a new `Preferences.tps`, a JSON file or a copy of a workbook (`style show`, `export`, `import`, `check`; also a Styles view in the GUI). Palettes only: it adds them to the colour picker and recolours nothing, and it has not been opened in Tableau.
- Runs as a Docker image behind a TLS proxy. From the next release, the image is also published to the GitHub Container Registry (`ghcr.io/ddsna/py-tbparse`).
- Compares two workbooks, scans a folder of them, and draws the data model as a graph.
- Works from Python, from the command line, or in a local browser page.

</details>

<details>
<summary><b>Install</b> (pip, extras, names)</summary>

```bash
pip install py-tbparse
```

For Excel input to templates, add the optional extra: `pip install "py-tbparse[excel]"` (it installs `openpyxl`).

Python 3.9 or newer. The package, the import and both commands all use the same name: `pip install py-tbparse`, `import py_tbparse`, `py-tbparse`, `py-tbparse-gui`. Releases up to 0.2.0 used `twbparser_py` and `twbparser`; those names are gone.

</details>

<details>
<summary><b>Quick start</b>: Python, command line, browser, across workbooks</summary>

From Python:

```python
from py_tbparse import TwbParser

p = TwbParser("workbook.twb")    # or a .twbx
p.get_overview()                 # counts of everything
p.get_calculated_fields()        # each calculation and its formula
p.get_relationships()            # how the tables connect
```

Every getter returns a DataFrame. The others are `get_datasources`, `get_parameters`, `get_fields`, `get_raw_fields`, `get_joins`, `get_relations`, `get_inferred_relationships`, `get_dashboards`, `get_dashboard_sheets`, `get_custom_sql`, `get_initial_sql`, `get_published_refs` and `get_field_usage`. `get_relationship_graph_dot()` returns the data model as Graphviz text and `validate()` looks for problems in the relationships. In Jupyter, a bare `p` shows the overview.

From the command line:

```bash
py-tbparse workbook.twb                    # overview
py-tbparse workbook.twb calculated-fields
py-tbparse workbook.twb fields --format csv -o fields.csv
py-tbparse workbook.twb validate           # exit code 2 if it finds a problem
```

In the browser:

```bash
py-tbparse-gui workbook.twb
```

Across workbooks:

```python
from py_tbparse import TwbParser, diff_workbooks, scan_folder

diff_workbooks(TwbParser("v1.twb"), TwbParser("v2.twb"), table="datasources")
scan_folder("./workbooks", table="datasources")   # one table, every workbook in the folder
```

</details>

<details>
<summary><b>Guides</b>: every command and feature in detail (docs/)</summary>

- [Command line](https://github.com/DDSNA/py-tbparse/blob/main/docs/cli.md): every table, the `diff`, `batch`, `rename`, `template`, `library`, `style` and `scaffold` commands, and their options.
- [Browser GUI](https://github.com/DDSNA/py-tbparse/blob/main/docs/gui.md): opening files, the table, the overview, the audit, the graph, themes, filling a template with new data, and making a template from the open workbook (Templates).
- [Running as a server](https://github.com/DDSNA/py-tbparse/blob/main/docs/deployment.md): the Docker image, a reverse proxy that ends TLS, sessions, limits.
- [Renaming](https://github.com/DDSNA/py-tbparse/blob/main/docs/renaming.md): clean names after a datasource switch, editing the suggestions, what will stay broken.
- [Templates](https://github.com/DDSNA/py-tbparse/blob/main/docs/templates.md): make a template from a workbook and apply it to new data.
- [Sanitize](https://github.com/DDSNA/py-tbparse/blob/main/docs/sanitize.md): the share-safe copy, its categories, the report and the optional synthetic data.
- [CI output and pre-commit](https://github.com/DDSNA/py-tbparse/blob/main/docs/ci.md): `--format junit|sarif|github`, exit codes, rule ids, sample workflow.
- [Prune](https://github.com/DDSNA/py-tbparse/blob/main/docs/prune.md): what it removes, what keeps a field, the report, the limits.
- [Slice](https://github.com/DDSNA/py-tbparse/blob/main/docs/slice.md): keep selected dashboards, what is dropped, actions, errors, the limits.
- [Audit and data dictionary](https://github.com/DDSNA/py-tbparse/blob/main/docs/audit.md): the audit rules A001 to A011, what "used" means, the Markdown data dictionary.
- [Libraries](https://github.com/DDSNA/py-tbparse/blob/main/docs/libraries.md): export calculated fields and parameters, add them to another workbook, what is not covered; also a Libraries view in the GUI.
- [Dashboard scaffolds](https://github.com/DDSNA/py-tbparse/blob/main/docs/scaffolds.md): make a dashboard layout from another one, what is kept and dropped, the integrity check, and what was not checked in Tableau.
- [Sheet copy](https://github.com/DDSNA/py-tbparse/blob/main/docs/sheet-copy.md): copy worksheets between workbooks, what is added and dropped, the clash policies, and what was not checked in Tableau. The library pieces under it are in [Sheet copy core](https://github.com/DDSNA/py-tbparse/blob/main/docs/sheet-copy-core.md).
- [Dashboard copy](https://github.com/DDSNA/py-tbparse/blob/main/docs/dashboard-copy.md): copy dashboards with their sheets between workbooks, what comes along, the clash policies, and what was not checked in Tableau.
- [Colour palettes](https://github.com/DDSNA/py-tbparse/blob/main/docs/styles.md): list, export and import named palettes, the clash policy, why nothing is recoloured and what was not checked in Tableau.
- [Normalised XML diff](https://github.com/DDSNA/py-tbparse/blob/main/docs/diff-xml.md): `py-tbparse diff-xml A B` and `normalised_diff()`, a line diff of two workbooks' XML that ignores attribute order, quotes and indentation.
- [`.twbx` files](https://github.com/DDSNA/py-tbparse/blob/main/docs/twbx.md): they are read straight from the zip; how to extract the contents.
- [Development](https://github.com/DDSNA/py-tbparse/blob/main/docs/development.md): running the tests, the workbook corpus, the browser tests.

</details>

<details>
<summary><b>Development, CI and deployment</b></summary>

- Running the tests, the 200-workbook corpus and the browser tests: [docs/development.md](https://github.com/DDSNA/py-tbparse/blob/main/docs/development.md).
- The code layout, the module table and the rules for porting a function from the R package: [AGENTS.md](https://github.com/DDSNA/py-tbparse/blob/main/AGENTS.md).
- CI output formats and the pre-commit hook: [docs/ci.md](https://github.com/DDSNA/py-tbparse/blob/main/docs/ci.md).
- The Docker image and running the GUI behind a TLS proxy: [docs/deployment.md](https://github.com/DDSNA/py-tbparse/blob/main/docs/deployment.md).
- The screenshots: `scripts/readme_screenshots.py` takes the pictures at the top of this page and in docs/gui.md (from the made-up demo workbook); `scripts/guide_screenshots.py` takes the user's guide pictures (`docs/guide-*.png`) from the public Superstore workbook in the corpus (`scripts/fetch_corpus.py` fetches it).

</details>

<details>
<summary><b>Why a Tableau parser</b></summary>

A `.twb` is XML and a `.twbx` is a zip containing one, so reading them from Python is not hard. Power BI's `.pbix` is a binary format built on a proprietary storage engine, and getting into it from code took reverse-engineering projects like [PBIXRay](https://github.com/Hugoberry/pbixray) and [pbi-tools](https://github.com/pbi-tools/pbi-tools). On the server side it goes the other way: Tableau's own Python tooling ([tableauserverclient](https://pypi.org/project/tableauserverclient/) and `tabcmd`) is more mature and more open than what Microsoft has for the Power BI REST API.

</details>

## Limits

- **Little of what the tool writes has been opened in Tableau.** Everything it writes is checked against Tableau's published schema and for dangling references, on 200 real workbooks. A template applied to a CSV and to a workbook has been opened in Tableau once, for one workbook, and drew its sheets (see [verify-in-tableau.md](https://github.com/DDSNA/py-tbparse/blob/main/docs/verify-in-tableau.md)); renamed workbooks, workbooks with a library added, palettes imported and other shapes have not. Open one on a copy and check it before relying on it. The original file is never modified or overwritten.
- **Only part of the R package is ported.** Missing: formatting, tooltips, colors, axes and sorts, dashboard layout and actions, calculation complexity, the replication brief and the Shiny inspector. The GUI covers some of what the inspector did.
- Where the R version has a bug, this one does not copy it: joins and relationships on more than one key, nested joins, the include-parameters option, and calculations with brackets inside brackets.
- **No login.** The GUI is meant to run on your own machine for one person. It refuses requests that come from other websites, but there is no login, so do not put it on a shared network. To share it, use the [Docker image](https://github.com/DDSNA/py-tbparse/blob/main/docs/deployment.md) behind a proxy that adds TLS and a login.

## Contributing

Issues and pull requests are welcome at [github.com/DDSNA/py-tbparse](https://github.com/DDSNA/py-tbparse). The test setup is in the [development guide](https://github.com/DDSNA/py-tbparse/blob/main/docs/development.md). `AGENTS.md` describes the code layout and the rules for porting a function from the R package.

## Credit

Based on [twbparser](https://github.com/PrigasG/twbparser) by George Arthur, MIT licensed. The user's guide pictures use `Brushing_Superstore_Sales_Map.twb` from [1230harry/TeamOne_MSc_Group_Project](https://github.com/1230harry/TeamOne_MSc_Group_Project) (MIT).

## License

MIT, see [LICENSE](https://github.com/DDSNA/py-tbparse/blob/main/LICENSE).
