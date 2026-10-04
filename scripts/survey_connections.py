#!/usr/bin/env python3
"""Survey the database connections Tableau wrote in the example-workbook corpus.

`py_tbparse/connections.py` copies what this prints, and `tests/test_targets.py` checks the registry against it, so
rerun it (after `python3 scripts/fetch_corpus.py`) whenever the corpus grows:

    python scripts/survey_connections.py [FOLDER]        # default tests/corpus/files

For every connection class: how many connections and workbooks use it, the attributes of its named connection (and
the values they take, secrets masked), the authentication values, how the relation names its table, whether the
metadata records are numbered from 0 or 1, which child tags a record has and in which order, and every
(local-type, remote-type, DebugRemoteType, DebugWireType, aggregation) combination with its count.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

from lxml import etree

DB_CLASSES = ("mysql", "postgres", "sqlserver", "snowflake")
SECRET = ("username", "password")


def _read(path: Path):
    if path.suffix.lower() == ".twbx":
        import zipfile
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".twb"))
            return etree.fromstring(z.read(name))
    return etree.parse(str(path)).getroot()


def survey(folder: Path) -> dict:
    """{class: {connections, workbooks, attributes: {name: Counter(values)}, tables: Counter(shape), ordinals: Counter,
    record_tags: Counter(tuple), types: Counter((local, remote, debug, wire, aggregation))}}"""
    out: dict = defaultdict(lambda: {
        "connections": 0, "workbooks": set(), "attributes": defaultdict(Counter), "tables": Counter(),
        "ordinals": Counter(), "record_tags": Counter(), "types": Counter(), "one_table_files": 0})
    for path in sorted(list(folder.glob("*.twb")) + list(folder.glob("*.twbx"))):
        try:
            root = _read(path)
        except Exception:
            continue
        for named in root.xpath("//datasource/connection[@class='federated']/named-connections/named-connection"):
            inner = named.find("connection")
            if inner is None or inner.get("class") not in DB_CLASSES:
                continue
            cls = inner.get("class")
            entry = out[cls]
            entry["connections"] += 1
            entry["workbooks"].add(path.name)
            for k, v in inner.attrib.items():
                entry["attributes"][k][("<secret>" if k in SECRET else v) if k not in ("server", "dbname", "schema")
                                       else "<name>"] += 1
            conn_id = named.get("name")
            fed = named.getparent().getparent()
            for rel in fed.xpath(".//*[local-name()='relation' or substring(name(), string-length(name()) - 10) = '...relation']"):
                if rel.get("connection") == conn_id and rel.get("type") == "table":
                    table = rel.get("table") or ""
                    entry["tables"][{1: "[table]", 2: "[schema].[table]", 3: "[db].[schema].[table]"}.get(
                        table.count("].[") + 1, "other")] += 1
                    entry["tables"]["has <columns> child" if rel.find("columns") is not None else "no <columns> child"] += 1
            records = fed.xpath("./metadata-records/metadata-record[@class='column']")
            if records:
                entry["ordinals"]["from " + (records[0].findtext("ordinal") or "?")] += 1
            for rec in records:
                if rec.findtext("local-name") is None:
                    continue
                tags = tuple(etree.QName(c).localname.split("...")[-1] for c in rec)
                entry["record_tags"][tags] += 1
                attrs = {a.get("name"): (a.text or "").strip('"') for a in rec.xpath("./attributes/attribute")}
                entry["types"][(rec.findtext("local-type"), rec.findtext("remote-type"),
                                attrs.get("DebugRemoteType", ""), attrs.get("DebugWireType", ""),
                                rec.findtext("aggregation"))] += 1
    return out


def main(argv: list[str]) -> int:
    folder = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent / "tests" / "corpus" / "files"
    if not folder.is_dir():
        print(f"no folder {folder}; run python3 scripts/fetch_corpus.py first", file=sys.stderr)
        return 2
    for cls, e in sorted(survey(folder).items()):
        print(f"\n== {cls}: {e['connections']} connections in {len(e['workbooks'])} workbooks")
        print("attributes (count of connections; values for the small sets):")
        for k, values in sorted(e["attributes"].items()):
            shown = ", ".join(f"{v!r} x{n}" for v, n in values.most_common(4)) if len(values) <= 6 else f"{len(values)} values"
            print(f"  {k}: {sum(values.values())}  {shown}")
        print("relations:", dict(e["tables"]))
        print("ordinals:", dict(e["ordinals"]))
        print("record child tags (most common first):")
        for tags, n in e["record_tags"].most_common(6):
            print(f"  {n:5d}  {' '.join(tags)}")
        print("types (local, remote, DebugRemoteType, DebugWireType, aggregation):")
        for combo, n in e["types"].most_common():
            print(f"  {n:5d}  {combo}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
