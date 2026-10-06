"""Normalised XML diff: show only the changes that mean something.

`canonical_lines()` writes a workbook's XML in a canonical, line-per-node form (attributes sorted, double
quotes, `&`/`<`/quote escapes as in Canonical XML, empty elements written open and closed, whitespace between
elements dropped, line endings as `\\n`), and `normalised_diff()` is a unified diff of two of those. Two files that
differ only in attribute order, quote style, indentation or `<a/>` versus `<a></a>` give an empty diff.

Text inside an element is kept exactly (a calculation's spaces matter), except that a text that is only
whitespace next to child elements is indentation and is dropped. Comments and processing instructions are kept,
including those before and after the root element (Tableau writes its build number as one). The XML declaration is not compared.
Nothing here is Tableau-specific; it takes `.twb`, `.twbx` (the workbook member), XML bytes or text, or a parsed tree.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Union

from lxml import etree

from ._xml import read_twb_from_twbx

_INDENT = "  "
_XML_NS = "http://www.w3.org/XML/1998/namespace"


def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True)


def _load(src) -> etree._Element:
    """The root element of a path (`.twb`/`.twbx`), bytes, XML text or parsed tree."""
    if isinstance(src, etree._ElementTree):
        return src.getroot()
    if isinstance(src, etree._Element):
        return src
    if isinstance(src, bytes):
        return etree.fromstring(src, _parser())
    if isinstance(src, str) and src.lstrip().startswith("<"):
        return etree.fromstring(src.encode("utf-8"), _parser())
    path = Path(src)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if path.suffix.lower() == ".twbx":
        return read_twb_from_twbx(str(path))["xml_doc"].getroot()
    return etree.parse(str(path), _parser()).getroot()


def _is_path(src) -> bool:
    return isinstance(src, Path) or (isinstance(src, str) and not src.lstrip().startswith("<"))


def _attr(value: str) -> str:
    return (value.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")
            .replace("\t", "&#x9;").replace("\n", "&#xA;").replace("\r", "&#xD;"))


def _text(value: str) -> str:
    return (value.replace("\r\n", "\n").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace("\r", "&#xD;"))


def _split(name: str) -> tuple[str, str]:
    if name.startswith("{"):
        ns, local = name[1:].split("}", 1)
        return ns, local
    return "", name


def _qname(el, name: str) -> str:
    ns, local = _split(name)
    if not ns:
        return local
    if ns == _XML_NS:
        return f"xml:{local}"
    for prefix, uri in el.nsmap.items():
        if uri == ns and prefix:
            return f"{prefix}:{local}"
    return local


def _open_tag(el: etree._Element, parent_ns: dict) -> str:
    parts = [_qname(el, el.tag)]
    ns_here = {p or "": u for p, u in el.nsmap.items() if parent_ns.get(p or "") != u}
    for prefix in sorted(ns_here):
        key = f"xmlns:{prefix}" if prefix else "xmlns"
        parts.append(f'{key}="{_attr(ns_here[prefix])}"')
    for name in sorted(el.attrib, key=_split):
        parts.append(f'{_qname(el, name)}="{_attr(el.attrib[name])}"')
    return " ".join(parts)


def _emit(el: etree._Element, depth: int, parent_ns: dict, out: list[str]) -> None:
    pad = _INDENT * depth
    if not isinstance(el.tag, str):  # comment or processing instruction
        out.append(pad + etree.tostring(el, encoding="unicode", with_tail=False).replace("\r\n", "\n"))
        return
    head = _open_tag(el, parent_ns)
    name = _qname(el, el.tag)
    children = list(el)
    text = el.text or ""
    if children and not text.strip():
        text = ""
    if not children:
        out.append(f"{pad}<{head}>{_text(text)}</{name}>")
        return
    out.append(f"{pad}<{head}>{_text(text)}")
    ns = {p or "": u for p, u in el.nsmap.items()}
    for child in children:
        _emit(child, depth + 1, ns, out)
        tail = child.tail or ""
        if tail.strip():
            out.append(_INDENT * (depth + 1) + _text(tail))
    out.append(f"{pad}</{name}>")


def canonical_lines(src: Union[str, Path, bytes, etree._Element, etree._ElementTree]) -> list[str]:
    """The workbook XML as canonical lines (see the module docstring)."""
    root = _load(src)
    out: list[str] = []
    for node in reversed(list(root.itersiblings(preceding=True))):  # comments before the root (Tableau's build comment)
        _emit(node, 0, {}, out)
    _emit(root, 0, {}, out)
    for node in root.itersiblings():
        _emit(node, 0, {}, out)
    return out


def normalised_diff(a, b, *, name_a: str | None = None, name_b: str | None = None, context: int = 3) -> str:
    """Unified diff of two XML documents after canonicalisation; `""` when there is no real difference.

    `a` and `b` are a path to a `.twb`/`.twbx`, XML bytes or text, or a parsed `lxml` tree. For a `.twbx` the
    workbook member is compared; the other archive members are not. The labels default to the file name
    (`a`/`b` for anything else).
    """
    la, lb = canonical_lines(a), canonical_lines(b)
    name_a = name_a or (Path(a).name if _is_path(a) else "a")
    name_b = name_b or (Path(b).name if _is_path(b) else "b")
    diff = list(difflib.unified_diff(la, lb, name_a, name_b, n=context, lineterm=""))
    return "\n".join(diff) + "\n" if diff else ""


def diff_line_count(a, b) -> int:
    """Added plus removed canonical lines (0 when the documents are equivalent)."""
    la, lb = canonical_lines(a), canonical_lines(b)
    return sum(1 for d in difflib.unified_diff(la, lb, n=0, lineterm="")
               if d[:1] in "+-" and not d.startswith(("+++", "---")))
