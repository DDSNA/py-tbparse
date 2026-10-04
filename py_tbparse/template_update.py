"""Bring a workbook made from a template up to date when the template has changed.

Stage A, `template_update_report()`: compare the revision a workbook was made from with a newer one and say,
change by change, what that does to the answers the workbook kept (its mapping and parameter values). Writes
nothing. Stage B, `update_from_answers()`: apply the new revision with those answers and stop at whatever
needs a person (a new required field with no column). A three-way merge of edits made to the workbook itself
is not here.

The "before" is the manifest the answers keep (`answers["template"]["manifest"]`, written since this module
exists), a template or manifest passed as `old=`, or, with neither, nothing: the report then only checks the
new template against the answers.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Optional, Union

import pandas as pd

from .templates import (
    Template,
    TemplateError,
    _answers_entries,
    _answers_entry,
    _type_status,
    apply_template,
    default_output_path,
    load_answers,
    load_template,
    read_data,
    resolve_apply,
)

REPORT_COLUMNS = ["kind", "datasource", "item", "change", "old", "new", "impact"]

# What a change does to the saved answers (empty: nothing to do).
AUTO_CARRY = "auto-carry"        # the saved choice still applies
NEEDS_MAPPING = "needs-mapping"  # a required field has no column
ORPHANED = "orphaned"            # the saved choice names something the template no longer has
TYPE_CONFLICT = "type-conflict"  # the saved choice no longer fits (column type, allowed value)
OPTIONAL = "optional"            # a new field no sheet needs; it gets a suggestion, or stays unmapped


def _manifest_of(source: Union[Template, dict, str, os.PathLike, None]) -> Optional[dict]:
    if source is None:
        return None
    if isinstance(source, dict):
        return source
    if isinstance(source, Template):
        return source.manifest
    return load_template(str(source)).manifest


def _unique_pairs(old: list[dict], new: list[dict], key) -> list[tuple[dict, dict]]:
    """Pairs of one old and one new field sharing a non-empty `key`, where nothing else shares it."""
    def index(fields):
        out: dict = {}
        for f in fields:
            k = key(f)
            if k:
                out.setdefault(k, []).append(f)
        return out
    a, b = index(old), index(new)
    return [(a[k][0], b[k][0]) for k in a if len(a[k]) == 1 and len(b.get(k, [])) == 1]


def _match_fields(old: list[dict], new: list[dict]) -> tuple[list[tuple[dict, dict]], list[dict], list[dict], list[tuple[dict, dict]]]:
    """(matched, removed, added, renamed). Matched by uid, then by name (a type or role change alters the
    uid, not the name); what is left is paired as a rename when it shares a source column (else a caption)
    with exactly one field on the other side."""
    matched: list[tuple[dict, dict]] = []
    old_left, new_left = list(old), list(new)
    for key in (lambda f: f.get("uid"), lambda f: f["name"]):
        pairs = _unique_pairs(old_left, new_left, key)
        matched += pairs
        done_old, done_new = {id(o) for o, _ in pairs}, {id(n) for _, n in pairs}
        old_left = [f for f in old_left if id(f) not in done_old]
        new_left = [f for f in new_left if id(f) not in done_new]
    renamed: list[tuple[dict, dict]] = []
    for key in (lambda f: f.get("remote"), lambda f: f.get("caption")):
        pairs = _unique_pairs(old_left, new_left, key)
        renamed += pairs
        done_old, done_new = {id(o) for o, _ in pairs}, {id(n) for _, n in pairs}
        old_left = [f for f in old_left if id(f) not in done_old]
        new_left = [f for f in new_left if id(f) not in done_new]
    return matched, old_left, new_left, renamed


def _physical(f: dict) -> Optional[str]:
    return f.get("physical_type") or f.get("datatype")


def _words(required: bool) -> str:
    return "required" if required else "optional"


class _Saved:
    """What the answers say, per template datasource and for parameters, plus the new data if it can be read."""

    def __init__(self, answers: dict, data=None):
        self.answers = answers
        self.data = data
        self.mapping = {e["datasource"]: dict(e.get("mapping") or {}) for e in _answers_entries(answers)}
        self.params = dict(answers.get("parameters") or {})

    def column_type(self, datasource: str, field: str) -> Optional[str]:
        column = self.mapping.get(datasource, {}).get(field)
        return self.data.datatype(column) if (self.data is not None and column) else None


def _field_impact(saved: Optional[_Saved], ds: str, change: str, o: Optional[dict], n: Optional[dict]) -> str:
    if saved is None:
        return ""
    mapped = (o or n)["name"] in saved.mapping.get(ds, {}) if change != "added" else False
    if change == "added":
        return NEEDS_MAPPING if n["required"] else OPTIONAL
    if change == "removed":
        return ORPHANED if mapped else ""
    if change == "type":
        if not mapped:
            return ""
        got = saved.column_type(ds, n["name"])
        if n.get("customized"):    # the author's own type wins; Tableau converts the column
            return AUTO_CARRY
        if got is None:            # no data to look at: cannot say it still fits
            return TYPE_CONFLICT
        return TYPE_CONFLICT if _type_status(_physical(n), got) == "type mismatch" else AUTO_CARRY
    if change == "required":
        return NEEDS_MAPPING if (n["required"] and not mapped) else (AUTO_CARRY if mapped else "")
    return AUTO_CARRY if mapped else ""    # renamed (the mapping moves with it), caption, role


def _diff(old: dict, new: dict, saved: Optional[_Saved]) -> tuple[list[dict], dict[str, dict[str, str]]]:
    """The rows of the report and the renames found, `{datasource: {old field name: new field name}}`."""
    rows: list[dict] = []
    renames: dict[str, dict[str, str]] = {}

    def row(kind, ds, item, change, o, n, impact=""):
        rows.append({"kind": kind, "datasource": ds, "item": item, "change": change,
                     "old": "" if o is None else str(o), "new": "" if n is None else str(n), "impact": impact})

    old_ds = {d["name"]: d for d in old.get("datasources", [])}
    new_ds = {d["name"]: d for d in new.get("datasources", [])}
    label = lambda d: d.get("caption") or d["name"]    # noqa: E731
    for name in old_ds.keys() - new_ds.keys():
        row("datasource", label(old_ds[name]), label(old_ds[name]), "removed", None, None,
            ORPHANED if saved is not None and saved.mapping.get(name) else "")
    for name in new_ds.keys() - old_ds.keys():
        row("datasource", label(new_ds[name]), label(new_ds[name]), "added", None, None)
    for name in [d["name"] for d in new.get("datasources", []) if d["name"] in old_ds]:
        o_ds, n_ds = old_ds[name], new_ds[name]
        ds = label(n_ds)
        matched, removed, added, renamed = _match_fields(o_ds["fields"], n_ds["fields"])
        for o, n in renamed:
            renames.setdefault(name, {})[o["name"]] = n["name"]
            row("field", ds, n["name"], "renamed", o["name"], n["name"], _field_impact(saved, name, "renamed", o, n))
            matched.append((o, n))    # a renamed field can have changed in other ways too
        for o in removed:
            row("field", ds, o["name"], "removed", _words(o["required"]), None, _field_impact(saved, name, "removed", o, None))
        for n in added:
            row("field", ds, n["name"], "added", None, _words(n["required"]), _field_impact(saved, name, "added", None, n))
        for o, n in matched:
            item = n["name"]
            if o.get("caption") != n.get("caption"):
                row("field", ds, item, "caption", o.get("caption"), n.get("caption"), _field_impact(saved, name, "caption", o, n))
            if o["required"] != n["required"]:
                row("field", ds, item, "required", _words(o["required"]), _words(n["required"]),
                    _field_impact(saved, name, "required", o, n))
            if (o["datatype"], _physical(o)) != (n["datatype"], _physical(n)):
                row("field", ds, item, "type", f"{o['datatype']} (data: {_physical(o)})", f"{n['datatype']} (data: {_physical(n)})",
                    _field_impact(saved, name, "type", o, n))
            if o.get("role") != n.get("role"):
                row("field", ds, item, "role", o.get("role"), n.get("role"), _field_impact(saved, name, "role", o, n))

    old_p = {p["caption"]: p for p in old.get("parameters", [])}
    new_p = {p["caption"]: p for p in new.get("parameters", [])}
    for caption in old_p.keys() - new_p.keys():
        row("parameter", "", caption, "removed", old_p[caption]["value"], None,
            ORPHANED if saved is not None and caption in saved.params else "")
    for caption in new_p.keys() - old_p.keys():
        row("parameter", "", caption, "added", None, new_p[caption]["value"])
    for caption in [p["caption"] for p in new.get("parameters", []) if p["caption"] in old_p]:
        o, n = old_p[caption], new_p[caption]
        held = saved is not None and caption in saved.params
        if o["datatype"] != n["datatype"]:
            row("parameter", "", caption, "type", o["datatype"], n["datatype"], TYPE_CONFLICT if held else "")
        if o["value"] != n["value"]:
            row("parameter", "", caption, "default", o["value"], n["value"], AUTO_CARRY if held else "")
        if (o.get("allowed") or []) != (n.get("allowed") or []):
            fits = not held or not n.get("allowed") or saved.params[caption] in n["allowed"]
            row("parameter", "", caption, "allowed values", "; ".join(o.get("allowed") or []) or "any",
                "; ".join(n.get("allowed") or []) or "any", (AUTO_CARRY if held else "") if fits else TYPE_CONFLICT)
    for kind, key in (("worksheet", "worksheets"), ("dashboard", "dashboards")):
        for name in sorted(set(old.get(key, [])) - set(new.get(key, []))):
            row(kind, "", name, "removed", None, None)
        for name in sorted(set(new.get(key, [])) - set(old.get(key, []))):
            row(kind, "", name, "added", None, None)
    return rows, renames


def _state_rows(new: dict, saved: _Saved) -> list[dict]:
    """With no "before": only what the new template and the answers say about each other."""
    rows: list[dict] = []
    for e in new.get("datasources", []):
        ds = e.get("caption") or e["name"]
        mapping = saved.mapping.get(e["name"])
        if mapping is None:
            continue
        names = {f["name"] for f in e["fields"]}
        for f in e["fields"]:
            if f["required"] and f["name"] not in mapping:
                rows.append({"kind": "field", "datasource": ds, "item": f["name"], "change": "no column saved",
                             "old": "", "new": "required", "impact": NEEDS_MAPPING})
            elif f["name"] in mapping:
                got = saved.column_type(e["name"], f["name"])
                if got and not f.get("customized") and _type_status(_physical(f), got) == "type mismatch":
                    rows.append({"kind": "field", "datasource": ds, "item": f["name"], "change": "type",
                                 "old": got, "new": _physical(f), "impact": TYPE_CONFLICT})
        for field in sorted(set(mapping) - names):
            rows.append({"kind": "field", "datasource": ds, "item": field, "change": "not in the template",
                         "old": mapping[field], "new": "", "impact": ORPHANED})
    params = {p["caption"]: p for p in new.get("parameters", [])}
    for caption, literal in sorted(saved.params.items()):
        if caption not in params:
            rows.append({"kind": "parameter", "datasource": "", "item": caption, "change": "not in the template",
                         "old": literal, "new": "", "impact": ORPHANED})
        elif params[caption].get("allowed") and literal not in params[caption]["allowed"]:
            rows.append({"kind": "parameter", "datasource": "", "item": caption, "change": "value not allowed",
                         "old": literal, "new": "; ".join(params[caption]["allowed"]), "impact": TYPE_CONFLICT})
    return rows


def _readable_data(answers: dict, datasource: Optional[str], data):
    """The new data, for type checks: the one passed, else the file the answers name; None when unreadable."""
    if data is not None:
        return read_data(str(data)) if not hasattr(data, "fields") else data
    entry = _answers_entry(answers, datasource) if datasource else (_answers_entries(answers) or [{}])[0]
    file = (entry.get("data") or {}).get("file")
    if not file:
        return None
    if not Path(file).is_absolute() and answers.get("_base_dir"):
        file = str(Path(answers["_base_dir"]) / file)
    try:
        return read_data(file, datasource=(entry.get("data") or {}).get("datasource"),
                         sheet=(entry.get("data") or {}).get("sheet"))
    except (OSError, ValueError):
        return None


def _prepare(template, workbook, old, data):
    new = template if isinstance(template, Template) else load_template(str(template))
    answers = load_answers(workbook if isinstance(workbook, dict) else str(workbook))
    saved_template = answers.get("template") or {}
    if new.id and saved_template.get("id") not in (None, new.id):
        raise TemplateError("these answers were made for another template "
                            f"(id {saved_template['id']}, this one is {new.id})")
    before = _manifest_of(old) or saved_template.get("manifest")
    first = (_answers_entries(answers) or [{}])[0].get("datasource")
    saved = _Saved(answers, _readable_data(answers, answers.get("datasource") or first, data))
    return new, answers, before, saved


def diff_template_revisions(old: Union[Template, dict, str], new: Union[Template, dict, str]) -> pd.DataFrame:
    """What changed between two revisions of a template, with no workbook involved (the `impact` column
    stays empty). Fields are matched by `uid`, then by name, then a field that kept its source column or
    caption but changed its local name counts as renamed. See `template_update_report` for the columns."""
    return pd.DataFrame(_diff(_manifest_of(old), _manifest_of(new), None)[0], columns=REPORT_COLUMNS)


def template_update_report(
    template: Union[Template, str],
    workbook: Union[str, os.PathLike, dict],
    old: Union[Template, dict, str, None] = None,
    data=None,
) -> pd.DataFrame:
    """What a newer template revision changes for a workbook made from an older one. Writes nothing.

    `workbook` is a workbook made by `apply_template`, or its answers (see `load_answers`). The "before" is
    `old` (a template, its manifest or its path), else the manifest the answers kept; with neither the
    report only checks the new template against the answers. Columns: `kind` (field, parameter, worksheet,
    dashboard, datasource), `datasource`, `item`, `change` (added, removed, renamed, caption, required, type,
    role, default, allowed values), `old`, `new`, and `impact` on the saved answers: `auto-carry`,
    `needs-mapping`, `orphaned`, `type-conflict`, `optional` (a new field no sheet needs), or empty. `data`
    is the new data file, read to check column types (default: the file the answers name, if it still reads).
    """
    new, answers, before, saved = _prepare(template, workbook, old, data)
    rows = _diff(before, new.manifest, saved)[0] if before else _state_rows(new.manifest, saved)
    return pd.DataFrame(rows, columns=REPORT_COLUMNS)


def update_from_answers(
    template: Union[Template, str],
    workbook: Union[str, os.PathLike, dict],
    output_path: Optional[str] = None,
    overwrite: bool = False,
    report: Optional[dict] = None,
    allow_missing: bool = False,
    mapping: Union[str, os.PathLike, pd.DataFrame, None] = None,
    old: Union[Template, dict, str, None] = None,
    data=None,
    datasource: Optional[str] = None,
    sheet: Union[str, int, None] = None,
) -> Optional[str]:
    """Apply a newer revision of a template to the data and answers of a workbook made from an older one;
    return the new workbook's path, or None when the answers were made from exactly this template (then
    there is nothing to do, and `report["status"]` is `"unchanged"`).

    Saved column choices follow a field that was renamed in the template. It stops with `TemplateError`
    when a required field has no column (a new one, or one whose saved column no longer fits), unless
    `allow_missing` (its sheets will break) or an edited `mapping` supplies it. A saved parameter value the
    template no longer accepts is dropped, so the parameter takes the template's default; `report` says
    which. `data` overrides the data file the answers name (`sheet` picks its worksheet, for Excel). The output defaults to
    `<workbook>_r<revision>.twbx` beside the workbook; nothing is overwritten unless `overwrite`.

    `report` is filled with `status`, `changes` (the stage A table), `needs_mapping`, `conflicts`,
    `dropped_parameters`, `columns_added`, `columns_removed`, `id_checked` (False when the template or the
    answers predate template ids, so they could not be matched) and `output`.
    """
    new, answers, before, saved = _prepare(template, workbook, old, data)
    report = report if report is not None else {}
    sha = (answers.get("template") or {}).get("manifest_sha256")
    if sha and sha == new.manifest_sha256:
        report.update(status="unchanged", changes=pd.DataFrame(columns=REPORT_COLUMNS), output=None)
        return None
    id_checked = bool(new.id and (answers.get("template") or {}).get("id"))
    entries = [e for e in _answers_entries(answers) if (e.get("data") or {}).get("file")]
    if datasource is None and len(entries) > 1:
        raise TemplateError("the workbook was made from several datasources; update handles one at a time "
                            "(pass datasource=)")
    rows, renames = _diff(before, new.manifest, saved) if before else (_state_rows(new.manifest, saved), {})
    changes = pd.DataFrame(rows, columns=REPORT_COLUMNS)

    carried = copy.deepcopy(answers)
    for entry in carried.get("datasources") or []:
        moved = renames.get(entry.get("datasource"), {})
        entry["mapping"] = {moved.get(f, f): c for f, c in (entry.get("mapping") or {}).items()}
    top = renames.get(carried.get("datasource"), {})
    carried["mapping"] = {top.get(f, f): c for f, c in (carried.get("mapping") or {}).items()}
    saved_params = carried.get("parameters") or {}
    params_by = {p["caption"]: p for p in new.manifest.get("parameters", [])}
    dropped = []
    for caption, literal in list(saved_params.items()):
        p = params_by.get(caption)
        if p is None or (p.get("allowed") and literal not in p["allowed"]):
            dropped.append(caption)
            del saved_params[caption]

    plan = resolve_apply(new, data, mapping=mapping, datasource=datasource, answers=carried, sheet=sheet)
    prior = _answers_entry(carried, plan.entry["name"])
    # a saved column whose type no longer fits the field is not kept: the field is asked for again
    conflicts = []
    by_field = {f["name"]: f for f in plan.entry["fields"]}
    if mapping is None:
        for i, r in plan.mapping.iterrows():
            f = by_field[r["field"]]
            if r["status"] == "from answers" and not f.get("customized") \
                    and _type_status(_physical(f), plan.data.datatype(r["mapped_to"])) == "type mismatch":
                conflicts.append(r["field"])
                plan.mapping.loc[i, ["mapped_to", "data_type", "score"]] = ["", "", None]
                plan.mapping.loc[i, "status"] = "type conflict"
    needs = [f for f in plan.entry["fields"] if f["required"] and not
             (plan.mapping.loc[plan.mapping["field"] == f["name"], "mapped_to"] != "").any()]
    before_cols = (prior.get("data") or {}).get("columns")
    report.update(
        status="updated", changes=changes, conflicts=conflicts, dropped_parameters=dropped, id_checked=id_checked,
        needs_mapping=[f["name"] for f in needs],
        columns_added=sorted(set(plan.data.names()) - set(before_cols)) if before_cols is not None else None,
        columns_removed=sorted(set(before_cols) - set(plan.data.names())) if before_cols is not None else None,
    )
    if needs and not allow_missing:
        sheets = sorted({s for f in needs for s in f.get("used_by") or []})
        raise TemplateError(
            "update stopped: no column for required field(s) "
            + ", ".join(f.get("caption") or f["name"].strip("[]") for f in needs)
            + (f"; sheets that would break: {', '.join(sheets)}" if sheets else "")
            + " (map them with mapping=, or pass allow_missing)")

    if output_path is None:
        src = Path(str(workbook))
        output_path = str(src.with_name(f"{src.stem}_r{new.revision}.twbx")) if src.suffix.lower() == ".twbx" \
            else default_output_path(new, plan.data)
    if not isinstance(workbook, dict) and Path(output_path).resolve() == Path(str(workbook)).resolve():
        raise FileExistsError(f"refusing to overwrite an input: {output_path}")
    out = apply_template(new, plan.data, mapping=plan.mapping, params=plan.params, output_path=output_path,
                         datasource=plan.entry["name"], allow_missing=allow_missing, overwrite=overwrite,
                         answers=carried)
    report["output"] = out
    return out
