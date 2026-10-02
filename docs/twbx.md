# Working with .twbx files

Part of [py-tbparse](https://github.com/DDSNA/py-tbparse).

A `.twbx` is read directly from the zip and nothing gets written to disk. That means `p.twbx_dir` is `None`, and `p.path` is a made-up `<file>.twbx/<name>.twb` that you can't open. If you want the files out, extract them yourself:

```python
from py_tbparse import extract_twb_from_twbx, twbx_extract_files

extract_twb_from_twbx("workbook.twbx", extract_dir="out/")
twbx_extract_files("workbook.twbx", exdir="out/")    # everything in the package
```
