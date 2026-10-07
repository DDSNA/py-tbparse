"""Datasource / connection / parameter extraction.

Ports of R/datasources.R (`extract_named_connections`,
`extract_datasource_details`) and the parameter half of
R/calculated_fields.R (`extract_parameters`).
"""

from __future__ import annotations

import re

import pandas as pd

from ._clean import attr_safe_get, basename_safe, clean_table, strip_brackets


def _coalesce(*vals):
    """First non-None value, unlike Python's `or` this keeps "" (matches
    R's `dplyr::coalesce()`/`%||%`, which only substitute on NA/NULL, not
    on empty strings)."""
    for v in vals:
        if v is not None:
            return v
    return None

_ATHENA_RE = re.compile(r"athena\.", re.IGNORECASE)
_ATHENA_REGION_RE = re.compile(r".*athena\.([^.]+)\..*")
_TRAILING_HEX32 = re.compile(r"_[0-9A-Fa-f]{32}$")

_DATASOURCE_COLUMNS = [
    "datasource", "primary_table", "connection_id", "connection_caption",
    "connection_class", "connection_target", "datasource_name",
    "field_count", "connection_type", "location",
]
_PARAMETER_COLUMNS = [
    "datasource", "name", "tableau_internal_name", "datatype", "role",
    "parameter_type", "allowable_type", "current_value", "is_parameter",
    "table", "table_clean",
]

_DATASOURCE_XPATH = (
    "/workbook/datasources/datasource[@name and not(ancestor::view)]"
)


def _location_named(cls, target, dbname, schema, region, fn) -> str:
    """Port of the `case_when` block in `extract_named_connections`."""
    if cls == "athena":
        label = "Athena"
        if region:
            label += f" ({region})"
        label += ": " + (dbname or "<catalog>")
        if schema:
            label += f".{schema}"
        return label
    if cls == "ogrdirect":
        return f"Shapefile: {basename_safe(fn)}"
    if cls in ("excel", "excel-direct"):
        return f"Excel: {basename_safe(fn)}"
    if cls == "textscan":
        return f"CSV: {basename_safe(fn)}"
    cls_title = (cls or "Unknown").title()
    return f"No Known File {cls_title}: {target or '<unknown>'}"


def extract_named_connections(xml_doc) -> pd.DataFrame:
    """Port of `extract_named_connections()`."""
    ncs = xml_doc.xpath("//named-connection")
    if not ncs:
        return pd.DataFrame()

    rows = []
    for nc in ncs:
        conn_id = nc.get("name")
        cap = nc.get("caption") or conn_id

        conn = nc.find("./connection")
        a = dict(conn.attrib) if conn is not None else {}

        cls = attr_safe_get(a, "class")
        server = attr_safe_get(a, "server")
        directory = attr_safe_get(a, "directory")
        fn = attr_safe_get(a, "filename")
        dbname = attr_safe_get(a, "dbname")
        schema = attr_safe_get(a, "schema")
        warehouse = attr_safe_get(a, "warehouse")

        target = _coalesce(server, directory, fn)

        region = None
        if server and _ATHENA_RE.search(server):
            # R's sub() returns the original (lowercased) string unchanged
            # when the finer region pattern doesn't match, rather than NA.
            low = server.lower()
            m = _ATHENA_REGION_RE.match(low)
            region = m.group(1) if m else low

        rows.append(
            {
                "connection_id": conn_id,
                "connection_caption": cap,
                "connection_class": cls,
                "connection_target": target,
                "dbname": dbname,
                "schema": schema,
                "warehouse": warehouse,
                "region": region,
                "filename": fn,
                "directory": directory,
                "location_named": _location_named(cls, target, dbname, schema, region, fn),
            }
        )
    return pd.DataFrame(rows)


def extract_parameters(xml_doc) -> pd.DataFrame:
    """Port of `extract_parameters()`."""
    ds_nodes = xml_doc.xpath(_DATASOURCE_XPATH)
    if not ds_nodes:
        return pd.DataFrame(columns=_PARAMETER_COLUMNS)

    rows = []
    for ds in ds_nodes:
        ds_name = ds.get("name")
        nodes = ds.xpath(".//column[@param-domain-type]")
        for node in nodes:
            a = dict(node.attrib)
            internal = attr_safe_get(a, "name")
            caption = attr_safe_get(a, "caption")
            raw_tbl = attr_safe_get(a, "table")

            cur = node.find(".//current-value")
            cur_val = cur.get("value") if cur is not None else None

            rows.append(
                {
                    "datasource": ds_name,
                    "name": caption if caption else strip_brackets(internal),
                    "tableau_internal_name": internal,
                    "datatype": attr_safe_get(a, "datatype"),
                    "role": attr_safe_get(a, "role"),
                    "parameter_type": attr_safe_get(a, "param-domain-type"),
                    "allowable_type": attr_safe_get(a, "data-type"),
                    "current_value": cur_val,
                    "is_parameter": True,
                    "table": raw_tbl,
                    "table_clean": clean_table(raw_tbl),
                }
            )
    return pd.DataFrame(rows, columns=_PARAMETER_COLUMNS).drop_duplicates()


_NOT_STORED = "not stored in the workbook"
_PARAMETERS_DATASOURCE = "Parameters"


def _first_text(*vals):
    """First non-empty string (an empty `server=''` says nothing about where the data is)."""
    for v in vals:
        if v:
            return v
    return None


def _real_datasources(xml_doc) -> list:
    """The `<datasource>` elements that hold data: everything but Tableau's internal
    `Parameters` datasource (its columns are the parameters, listed in their own table)."""
    return [
        ds for ds in xml_doc.xpath(_DATASOURCE_XPATH)
        if ds.get("name") != _PARAMETERS_DATASOURCE
    ]


def _own_connection(ds) -> dict:
    """What a datasource says about its own connection, for rows with no named connection."""
    conn = ds.find(".//connection")
    if conn is None:
        return {}
    a = dict(conn.attrib)
    cls = attr_safe_get(a, "class")
    server = attr_safe_get(a, "server")
    filename = attr_safe_get(a, "filename")
    if cls == "excel":
        location = f"Excel: {basename_safe(filename) if filename else '<unknown>'}"
    elif cls == "textscan":
        location = f"CSV: {basename_safe(filename) if filename else '<unknown>'}"
    elif cls == "federated":
        location = f"Federated: {server or '<unknown>'}"
    else:
        location = f"No Known File {(cls or 'Unknown').title()}: {server or '<unknown>'}"
    return {
        "connection_class": cls,
        "connection_target": _first_text(server, attr_safe_get(a, "directory"), filename),
        "location": location,
    }


def _owner(rel, real, by_table, by_conn=None):
    """The datasource a logical table belongs to: the `<datasource>` the object graph sits in,
    else the one whose own relations name the table, else the only datasource that declares
    the relation's named connection (issue #79), else the only real datasource."""
    for anc in rel.xpath("ancestor::datasource"):
        if any(anc is d for d in real):
            return anc
    owner = by_table.get(rel.get("table"))
    if owner is not None:
        return owner
    owner = (by_conn or {}).get(rel.get("connection"))
    if owner is not None:
        return owner
    return real[0] if len(real) == 1 else None


def _table_field_count(ds, name):
    """Fields of one logical table: the datasource's `metadata-record` columns whose
    `parent-name` is `[name]` (issue #79). Object-model workbooks list each table twice, as
    `[Orders]` and `[Orders_<32 hex>]`; the plain name wins, else the copy is counted once.
    None when the workbook says nothing about this table (the caller keeps the whole count)."""
    if ds is None or not name:
        return None
    plain, copies = set(), set()
    for rec in ds.iterfind(".//metadata-record[@class='column']"):
        parent = rec.findtext("parent-name")
        if not parent:
            continue
        local = rec.findtext("local-name") or rec.findtext("remote-name") or ""
        base = strip_brackets(parent.strip())
        if base == name:
            plain.add(local)
        elif _TRAILING_HEX32.sub("", base) == name:
            copies.add(local)
    found = plain or copies
    return len(found) if found else None


def extract_datasource_details(xml_doc) -> dict:
    """Port of `extract_datasource_details()` (reworked for issue #65).

    One row per logical table of the object graph (per datasource when there is no graph),
    never one for the internal `Parameters` datasource. A row's connection comes from its
    relation's named connection; its datasource name from the datasource it sits in; its field
    count from the metadata of its own table (the datasource's whole count when the workbook lists none); whatever the workbook does not store reads "not stored in the workbook".

    Returns a dict with `data_sources`, `parameters`, `all_sources`.
    """
    real = _real_datasources(xml_doc)
    by_table = {}
    for ds in real:
        for r in ds.xpath(".//relation[@type='table']"):
            by_table.setdefault(r.get("table"), ds)

    # named connection -> its datasource, only when exactly one real datasource declares it
    by_conn, clashes = {}, set()
    for ds in real:
        for nc in ds.iterfind(".//named-connection"):
            n = nc.get("name")
            if n in by_conn and by_conn[n] is not ds:
                clashes.add(n)
            by_conn.setdefault(n, ds)
    for n in clashes:
        del by_conn[n]

    conn_meta = extract_named_connections(xml_doc)
    conns = (
        {r["connection_id"]: r for r in conn_meta.astype(object).where(conn_meta.notna(), None)
         .to_dict("records")}
        if "connection_id" in conn_meta.columns else {}
    )

    rels = xml_doc.xpath(
        "//*[contains(local-name(), 'object-graph')]"
        "//object//properties[@context='']/relation[@type='table']"
    )
    # (datasource element or None, relation name, table, connection id)
    entries = []
    seen = set()
    for r in rels:
        owner = _owner(r, real, by_table, by_conn)
        key = (id(owner), r.get("name"), r.get("table"), r.get("connection"))
        if key not in seen:
            seen.add(key)
            entries.append((owner, r.get("name"), r.get("table"), r.get("connection")))
    covered = {id(o) for o, *_ in entries if o is not None}
    for ds in real:
        if id(ds) in covered:
            continue
        rel = ds.find(".//relation[@type='table']")
        if rel is not None:
            entries.append((ds, rel.get("name"), rel.get("table"), rel.get("connection")))
        else:
            nc = ds.find(".//named-connection")
            entries.append((ds, ds.get("caption") or ds.get("name"), None,
                            nc.get("name") if nc is not None else None))

    def _field_count(ds, name):
        if ds is None:
            return 0
        own = _table_field_count(ds, name)
        return len(ds.findall(".//column")) if own is None else own

    rows = []
    for ds, name, table, conn_id in entries:
        own = _own_connection(ds) if ds is not None else {}
        if conn_id is None and ds is not None:
            nc = ds.find(".//named-connection")
            if nc is not None and ds.find(".//relation[@type='table']") is None:
                conn_id = nc.get("name")
        c = conns.get(conn_id, {})
        cls = _first_text(c.get("connection_class"), own.get("connection_class"))
        rows.append(
            {
                "datasource": name,
                "primary_table": table,
                "connection_id": conn_id,
                "connection_caption": _first_text(c.get("connection_caption")) or _NOT_STORED,
                "connection_class": cls or _NOT_STORED,
                "connection_target": _first_text(
                    c.get("connection_target"), c.get("directory"), c.get("filename"), own.get("connection_target")
                ) or _NOT_STORED,
                "datasource_name": (ds.get("name") if ds is not None else None)
                or _first_text(c.get("connection_caption")) or _NOT_STORED,
                "field_count": _field_count(ds, name),
                "connection_type": cls or _NOT_STORED,
                "location": _first_text(c.get("location_named"), own.get("location")) or _NOT_STORED,
            }
        )
    final = pd.DataFrame(rows, columns=_DATASOURCE_COLUMNS)
    final["field_count"] = final["field_count"].astype(int)

    try:
        params = extract_parameters(xml_doc)
    except Exception:
        params = pd.DataFrame(columns=_PARAMETER_COLUMNS)

    return {"data_sources": final, "parameters": params, "all_sources": final}
