# Data dictionary: filtering

| Property | Value |
| --- | --- |
| File | `filtering.twb` |
| Tableau file version | `18.1` |
| Saved by | `2021.1.2 (20211.21.0511.0935)` |
| Datasources | 1 |
| Fields | 42 |
| Calculated fields | 1 |
| Parameters | 0 |
| Worksheets | 2 |
| Dashboards | 1 |

This page was read from the workbook file by py-tbparse. Nothing was opened in Tableau, and "used by" follows worksheets, dashboards and calculations only (see `docs/audit.md`).

## Datasources

### Datasource: TestData (EmptyDB)

| Connection |
| --- |
| `class=sqlserver; server=b5dpm3ihhu.database.windows.net; dbname=EmptyDB; authentication=sqlserver` |

#### Fields (42)

| Field | Caption | Type | Role | Kind | Formula | Used by |
| --- | --- | --- | --- | --- | --- | --- |
| `Account Account Name` |  | string |  | physical |  | (nothing) |
| `Account Number` |  | real | dimension | physical |  | (nothing) |
| `Account Number Burst Out Account` |  | string |  | physical |  | (nothing) |
| `Acct Name` |  | string |  | physical |  | (nothing) |
| `Amount` |  | string |  | physical |  | (nothing) |
| `Amount1` |  | string |  | physical |  | (nothing) |
| `Burst Out` |  | string |  | physical |  | (nothing) |
| `Burst Out Join` |  | string |  | physical |  | (nothing) |
| `Burst Out Set list` |  | string | dimension | physical |  | Sheets: Sheet 1; Sheet 2 / Dashboards: setTest / Calculations: BurstoutSet; SHOW |
| `Burst Out View` |  | real |  | physical |  | (nothing) |
| `BurstoutSet` | BurstoutSet |  |  | group |  | Sheets: Sheet 1; Sheet 2 / Dashboards: setTest / Calculations: SHOW |
| `Count JE Number` |  | real |  | physical |  | (nothing) |
| `Count of Amount Calculation` |  | real |  | physical |  | (nothing) |
| `Entity ID` |  | string |  | physical |  | (nothing) |
| `Filter` |  | real |  | physical |  | (nothing) |
| `Fiscal Year` |  | string |  | physical |  | (nothing) |
| `Flag` |  | boolean |  | physical |  | (nothing) |
| `Flag__copy_` |  | boolean |  | physical |  | (nothing) |
| `FS Line` |  | real |  | physical |  | (nothing) |
| `FS Line Burst Out Account` |  | string |  | physical |  | (nothing) |
| `Group By` |  | real |  | physical |  | (nothing) |
| `Image` |  | string |  | physical |  | (nothing) |
| `Note Line` |  | real |  | physical |  | (nothing) |
| `Note Line Burst Out Account` |  | string |  | physical |  | (nothing) |
| `Number of Records` |  | real | measure | physical |  | Sheets: Sheet 1 / Dashboards: setTest |
| `Number of Records1` |  | real |  | physical |  | (nothing) |
| `Select Burst Out` |  | real |  | physical |  | (nothing) |
| `Select Transaction Analysis view` |  | real |  | physical |  | (nothing) |
| `Selection` |  | real |  | physical |  | (nothing) |
| `Calculation_88946136969252864` | SHOW | string | dimension | calculated | `IF [BurstoutSet] THEN "Selected" ELSE "Not Selected" END` | Sheets: Sheet 1 / Dashboards: setTest |
| `show` | Show | string | dimension | physical |  | (nothing) |
| `Show Cycle Based` |  | string |  | physical |  | (nothing) |
| `Sub Class` |  | real |  | physical |  | (nothing) |
| `SubClass Burst Out Account` |  | string |  | physical |  | (nothing) |
| `Sum Cy` |  | real |  | physical |  | (nothing) |
| `Sum Py1` |  | real |  | physical |  | (nothing) |
| `Sum Py2` |  | real |  | physical |  | (nothing) |
| `Sum Py3` |  | real |  | physical |  | (nothing) |
| `Sum Py4` |  | real |  | physical |  | (nothing) |
| `Total Credits` |  | real |  | physical |  | (nothing) |
| `Total Debits` |  | real |  | physical |  | (nothing) |
| `Type` |  | string |  | physical |  | (nothing) |

## Parameters

None.

## Worksheets (where fields are used)

| Worksheet | Hidden | On dashboards | Fields it uses directly |
| --- | --- | --- | --- |
| Sheet 1 |  | setTest | Burst Out Set list; Number of Records; SHOW |
| Sheet 2 |  | setTest | Burst Out Set list; BurstoutSet |

## Dashboards

| Dashboard | Worksheets |
| --- | --- |
| setTest | Sheet 1; Sheet 2 |
