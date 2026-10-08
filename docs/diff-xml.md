# Normalised XML diff

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse).

Two saves of the same workbook rarely match byte for byte: attribute order, quote style, indentation and `<a/>` versus
`<a></a>` all change when a file is written by another tool. `diff-xml` removes that noise so a diff shows only what
changed in the workbook.

```bash
py-tbparse diff-xml before.twb after.twb          # unified diff on stdout
py-tbparse diff-xml before.twbx after.twbx -U 0 -o changes.diff
```

Exit code 0: no differences. 1: differences. 2: a file cannot be read, or `-o` names one of the inputs. Every command's codes: [cli.md](cli.md#exit-codes).
For a `.twbx` only the workbook (`.twb`) member is compared; data, extracts and images are not.

In Python:

```python
from py_tbparse import normalised_diff
text = normalised_diff("before.twb", "after.twb")     # "" when equivalent
```

Inputs may be paths, XML bytes or text, or parsed `lxml` trees.

## What counts as a difference

Each file is written out one node per line, indented, with attributes sorted, double quotes, the escapes of Canonical
XML and every element open and closed. Then the two are compared as text. So these are ignored: attribute order, `'`
versus `"`, indentation and blank lines between elements, empty-element style, `\r\n` versus `\n`, the XML
declaration. These are real differences: any attribute or text value (a calculation's spaces count), element order,
comments (including the build comment before the root element).

It is a canonical form in the spirit of lxml's `method="c14n"`, not that function's output: c14n puts the whole
document on one line, which cannot be diffed.

## Measured on the corpus

`scripts/measure_roundtrip_diff.py` saves every workbook of `tests/corpus/files` (200 `.twb`) through the writer
py-tbparse uses for rename, templates and styles, with no edits, and counts differing lines against the original:

| Comparison | Files with no differing line | Median lines | Max lines |
|---|---|---|---|
| plain text diff | 0 of 200 | 830 | 7570 |
| `diff-xml` | 200 of 200 | 0 | 0 |

So the writer changes formatting only, never content, on that corpus. That says nothing about whether Tableau opens a
file; nothing here was checked in Tableau.
