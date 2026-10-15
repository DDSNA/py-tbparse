"""Public path parameters take a `pathlib.Path` as well as a `str` (issue #187).

Every public function that takes a file or folder is called twice, once with `str` paths and once with
`pathlib.Path` ones, in two identical scratch folders; the results must match. A second test checks that no
public path parameter is annotated as a plain `str` any more.
"""

import inspect
import os
import shutil
import sys
import typing
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent))

import py_tbparse  # noqa: E402
from py_tbparse import (  # noqa: E402
    TwbParser, apply_field_renames, apply_scaffold, apply_template, apply_template_folder, audit, check_drift,
    check_style_file, check_template, compare_field_schemas, diff_template_revisions, export_library,
    export_palettes, extract_twb_from_twbx, import_library, import_palettes, load_answers, load_library,
    load_mapping, load_rename_mapping, load_scaffold, load_style, load_template, make_scaffold, make_template, prune,
    read_data, read_many, read_palettes, resolve_apply, sanitize, save_library, save_scaffold, save_style,
    scan_folder, slice_workbook, suggest_field_renames, suggest_renames, template_update_report,
    twbx_extract_files, twbx_list, update_from_answers, validate_workbook,
)

FIXTURES = Path(__file__).parent / "fixtures"
PUBLIC = FIXTURES / "public"


def build_workspace(root: Path) -> dict:
    """The same files in `root` every time, so a `str` run and a `Path` run see identical inputs."""
    root.mkdir()
    for name in ("Cache.twbx", "filtering.twb"):
        shutil.copy(PUBLIC / name, root / name)
    shutil.copy(FIXTURES / "test_for_wenjie.twb", root / "wenjie.twb")
    shutil.copy(FIXTURES / "test_for_zip.twbx", root / "zip.twbx")
    shutil.copy(FIXTURES / "library" / "source.twb", root / "lib_source.twb")
    shutil.copy(FIXTURES / "library" / "target.twb", root / "lib_target.twb")
    shutil.copy(FIXTURES / "style" / "palettes.twb", root / "palettes.twb")
    shutil.copy(FIXTURES / "style" / "Preferences.tps", root / "Preferences.tps")
    shutil.copy(FIXTURES / "templates" / "filtering.v1.template.twbx", root / "v1.template.twbx")
    tmpl = Path(make_template(str(root / "Cache.twbx"), output_path=str(root / "cache.template.twbx"),
                              template_id="tpl-1"))
    header = [f["remote"] for f in load_template(tmpl).manifest["datasources"][0]["fields"]]
    sample = {"string": "x", "date": "2026-01-31"}
    types = [f["datatype"] for f in load_template(tmpl).manifest["datasources"][0]["fields"]]
    data = root / "data" / "data.csv"
    data.parent.mkdir()
    data.write_text(",".join(header) + "\n" + ",".join(sample.get(t, "1") for t in types) + "\n", encoding="utf-8")
    ds_name = load_template(tmpl).manifest["datasources"][0]["name"]
    applied = apply_template(str(tmpl), str(data), datasource=ds_name, allow_missing=True,
                             output_path=str(root / "applied.twbx"))
    (root / "out").mkdir()
    (root / "mapping.csv").write_text("field,mapped_to\nA,B\n", encoding="utf-8")
    (root / "renames.csv").write_text("kind,datasource,name,suggested,reason\n", encoding="utf-8")
    return {"root": root, "tmpl": tmpl, "data": data, "ds": ds_name, "applied": Path(applied),
            "wb": root / "wenjie.twb", "dash": root / "filtering.twb", "twbx": root / "zip.twbx", "cache": root / "Cache.twbx"}


def norm(value, root: Path):
    """A comparable form of a result: frames as records, paths relative to the scratch folder, no temp noise."""
    if isinstance(value, pd.DataFrame):
        return [norm(r, root) for r in value.to_dict("records")]
    if isinstance(value, dict):
        return {str(k): norm(v, root) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [norm(v, root) for v in value]
    if isinstance(value, Path):
        raise AssertionError(f"a pathlib.Path leaked into a result: {value}")
    if isinstance(value, str):
        return value.replace(str(root), "<root>")
    return value


def written(path, root: Path):
    """A written file by name, type and existence (zip timestamps and generated ids vary between runs)."""
    assert isinstance(path, str), f"expected a str path back, got {type(path).__name__}"
    return (Path(path).relative_to(root).as_posix(), Path(path).exists())


def sheet_names(ws):
    doc = TwbParser(str(ws["dash"])).xml_doc
    return doc.xpath("/workbook/worksheets/worksheet/@name")[:2]


def first_dashboard(ws):
    return TwbParser(str(ws["dash"])).get_dashboards()["name"].iloc[0]


# Each case: fn(c, ws) -> a comparable result. `c` turns a path into a str or a Path.
CASES = {
    "TwbParser": lambda c, ws: (TwbParser(c(ws["wb"])).get_overview(), TwbParser(c(ws["twbx"])).get_overview()),
    "TwbParser.path_is_str": lambda c, ws: [type(TwbParser(c(p)).path).__name__ for p in (ws["wb"], ws["twbx"])],
    "twbx_list": lambda c, ws: twbx_list(c(ws["twbx"])),
    "extract_twb_from_twbx": lambda c, ws: (lambda r: (Path(r["twb_path"]).relative_to(ws["root"]).as_posix(),
                                                     type(r["exdir"]).__name__, type(r["twbx_path"]).__name__))(
        extract_twb_from_twbx(c(ws["twbx"]), extract_dir=c(ws["root"] / "ex"), extract_all=True)),
    "twbx_extract_files": lambda c, ws: twbx_extract_files(c(ws["twbx"]), exdir=c(ws["root"] / "ex2")).assign(
        path=lambda d: d["path"].map(lambda p: Path(p).relative_to(ws["root"]).as_posix())
        if "path" in d else None),
    "scan_folder": lambda c, ws: scan_folder(c(ws["root"])),
    "validate_workbook": lambda c, ws: validate_workbook(c(ws["wb"])),
    "audit": lambda c, ws: audit(c(ws["cache"])),
    "make_scaffold/save_scaffold/load_scaffold": lambda c, ws: (
        lambda sc: (save_scaffold(sc, c(ws["root"] / "s.json")) and load_scaffold(c(ws["root"] / "s.json")) == sc)
    )(make_scaffold(c(ws["dash"]), dashboard=first_dashboard(ws))),
    "apply_scaffold": lambda c, ws: written(apply_scaffold(
        c(ws["dash"]), make_scaffold(c(ws["dash"]), dashboard=first_dashboard(ws)),
        "Copy", sheets=sheet_names(ws), allow_empty=True, output_path=c(ws["root"] / "out" / "scaffold.twb")), ws["root"]),
    "apply_field_renames": lambda c, ws: written(apply_field_renames(
        TwbParser(str(ws["wb"])), pd.DataFrame(columns=["kind", "datasource", "name", "suggested", "reason"]),
        output_path=c(ws["root"] / "out" / "renamed.twb"), overwrite=True), ws["root"]),
    "compare_field_schemas": lambda c, ws: compare_field_schemas(TwbParser(str(ws["wb"])), reference=c(ws["wb"])),
    "suggest_field_renames": lambda c, ws: suggest_field_renames(TwbParser(str(ws["wb"])), reference=c(ws["wb"])),
    "suggest_renames": lambda c, ws: suggest_renames(TwbParser(str(ws["wb"])), reference=c(ws["wb"])),
    "load_rename_mapping": lambda c, ws: load_rename_mapping(c(ws["root"] / "renames.csv")),
    "make_template": lambda c, ws: written(make_template(
        c(ws["cache"]), output_path=c(ws["root"] / "out" / "t.twbx"), revision_of=c(ws["tmpl"])), ws["root"]),
    "load_template": lambda c, ws: load_template(c(ws["tmpl"])).manifest["datasources"],
    "read_data": lambda c, ws: norm(read_data(c(ws["data"])).fields, ws["root"]),
    "load_mapping": lambda c, ws: load_mapping(c(ws["root"] / "mapping.csv")),
    "apply_template": lambda c, ws: written(apply_template(
        c(ws["tmpl"]), c(ws["data"]), datasource=ws["ds"], allow_missing=True,
        output_path=c(ws["root"] / "out" / "a.twbx")), ws["root"]),
    "resolve_apply": lambda c, ws: resolve_apply(c(ws["tmpl"]), c(ws["data"]), datasource=ws["ds"]).mapping,
    "apply_template_folder": lambda c, ws: apply_template_folder(
        c(ws["tmpl"]), c(ws["data"].parent), output_dir=c(ws["root"] / "out" / "folder"), min_mapped=0.0,
        datasource=ws["ds"]).drop(columns=["output"], errors="ignore"),
    "load_answers": lambda c, ws: norm(load_answers(c(ws["applied"])), ws["root"]) and True,
    "diff_template_revisions": lambda c, ws: diff_template_revisions(c(ws["tmpl"]), c(ws["tmpl"])),
    "template_update_report": lambda c, ws: template_update_report(c(ws["tmpl"]), c(ws["applied"])),
    "update_from_answers": lambda c, ws: written(update_from_answers(
        make_template(c(ws["cache"]), output_path=c(ws["root"] / "out" / "rev2.twbx"), revision_of=c(ws["tmpl"])),
        c(ws["applied"]), output_path=c(ws["root"] / "out" / "u.twbx"), allow_missing=True),
        ws["root"]),
    "check_template": lambda c, ws: check_template(c(ws["tmpl"])),
    "check_drift": lambda c, ws: check_drift(c(ws["tmpl"]), c(ws["data"].parent)),
    "read_many": lambda c, ws: [(p.name, p.status, p.rows) for p in read_many(c(ws["data"])).parts],
    "prune": lambda c, ws: written(prune(c(ws["wb"]), output_path=c(ws["root"] / "out" / "p.twb"))["output"]
                                   or str(ws["root"] / "out" / "p.twb"), ws["root"]),
    "slice_workbook": lambda c, ws: norm(slice_workbook(
        c(ws["dash"]), first_dashboard(ws),
        output_path=c(ws["root"] / "out" / "sl.twb")), ws["root"]),
    "sanitize": lambda c, ws: written(sanitize(c(ws["wb"]), c(ws["root"] / "out" / "san.twb")), ws["root"]),
    "export_library/save_library/load_library": lambda c, ws: (
        lambda lib: (save_library(lib, c(ws["root"] / "lib.json")) and load_library(c(ws["root"] / "lib.json")) == lib)
    )(export_library(TwbParser(str(ws["root"] / "lib_source.twb")))),
    "import_library": lambda c, ws: written(import_library(
        TwbParser(str(ws["root"] / "lib_target.twb")),
        (save_library(export_library(TwbParser(str(ws["root"] / "lib_source.twb"))), c(ws["root"] / "lib.json")) and
         c(ws["root"] / "lib.json")), on_clash="rename", output_path=c(ws["root"] / "out" / "imp.twb")), ws["root"]),
    "read_palettes": lambda c, ws: (read_palettes(c(ws["root"] / "palettes.twb")),
                                    read_palettes(c(ws["root"] / "Preferences.tps"))),
    "save_style/load_style/check_style_file": lambda c, ws: (
        save_style({"format": "py-tbparse-style", "version": 1, "palettes": []}, c(ws["root"] / "st.json")) and True,
        check_style_file(c(ws["root"] / "st.json")), load_style(c(ws["root"] / "st.json"))),
    "import_palettes": lambda c, ws: written(import_palettes(
        c(ws["root"] / "lib_target.twb"), c(ws["root"] / "palettes.twb"),
        output_path=c(ws["root"] / "out" / "pal.twb")), ws["root"]),
    "export_palettes": lambda c, ws: written(export_palettes(
        [c(ws["root"] / "palettes.twb")], c(ws["root"] / "out" / "Preferences.tps")), ws["root"]),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_path_gives_the_same_result_as_the_str(tmp_path, name):
    str_ws = build_workspace(tmp_path / "s")
    path_ws = build_workspace(tmp_path / "p")
    by_str = CASES[name](str, str_ws)
    by_path = CASES[name](lambda p: Path(p), path_ws)
    assert norm(by_path, path_ws["root"]) == norm(by_str, str_ws["root"])


# Parameters that look like paths but are not, or whose type is fixed on purpose.
NOT_A_PATH = {
    ("Template", "path"): "dataclass field; load_template fills it with the str path it was opened from",
    ("palettes_from_bytes", "filename"): "a name used to pick the parser by extension, not opened",
    ("format_findings", "path"): "a label shown in the output, never opened",
    ("export_library", "folder"): "a folder of the datasource (Tableau's own), not a directory",
}
PATH_PARAM_NAMES = {"path", "twbx_path", "extract_dir", "exdir", "directory", "output_dir", "output_path",
                    "workbook", "wb", "source", "reference", "template", "data", "mapping", "answers", "inputs"}


def _public_callables():
    for name in py_tbparse.__all__:
        obj = getattr(py_tbparse, name)
        if inspect.isclass(obj) and issubclass(obj, BaseException):
            continue
        if inspect.isclass(obj):
            yield name, obj.__init__
        elif callable(obj):
            yield name, obj


def _flat_types(hint):
    """Every type named inside a (possibly nested) Union/Optional."""
    if typing.get_origin(hint) is typing.Union:
        for arg in typing.get_args(hint):
            yield from _flat_types(arg)
    else:
        yield hint


def _names_pathlike(types) -> bool:
    return any(t is os.PathLike or typing.get_origin(t) is os.PathLike for t in types)


def _hints(fn) -> dict:
    """`typing.get_type_hints(fn)`, one parameter at a time: on Python 3.9 an unrelated `X | None` annotation
    elsewhere in a signature cannot be evaluated and would otherwise hide the path parameters."""
    out = {}
    for param, ann in getattr(fn, "__annotations__", {}).items():
        if isinstance(ann, str):
            try:
                ann = eval(ann, getattr(fn, "__globals__", {}))  # noqa: S307 - our own annotation strings
            except TypeError:
                continue
        out[param] = ann
    return out


def test_no_public_path_parameter_is_a_plain_str():
    offenders = []
    checked = 0
    for name, fn in _public_callables():
        hints = _hints(fn)
        for param in inspect.signature(fn).parameters:
            if (name, param) in NOT_A_PATH or param not in PATH_PARAM_NAMES or param not in hints:
                continue
            checked += 1
            types = set(_flat_types(hints[param]))
            if str in types and not _names_pathlike(types):
                offenders.append(f"{name}({param})")
    assert checked > 20  # the introspection found the public path parameters
    assert not offenders, f"a path parameter that names str must also accept os.PathLike: {offenders}"
