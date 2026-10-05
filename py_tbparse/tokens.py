"""Template tokens: `{{customer}}` written as plain text in a title, a text box, a caption or a string parameter,
filled in with a different value for every workbook an apply makes.

Syntax: `{{name}}`, where `name` starts with a letter and continues with letters, digits, `_`, `-` or a space (the
spaces around it are ignored; names are case-sensitive). A literal `{{` is written `{{{{` and a literal `}}` is `}}}}`.

Tokens live only where a person types text (the places below), never in a formula or in SQL: replacing inside a
formula would change what a calculation means, so a token found there is reported by `formula_hits` and left alone.
Each place has its own XPath; nothing is a blind string replace over the XML. A token typed in any other text run
(a tooltip, an annotation, an axis title) is left as typed and reported by `unscanned_hits`.

A token has to sit inside one text run. Tableau starts a new run where the formatting changes, so format a whole
token the same way (a token cut by a format change is found by `broken_hits` and reported).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as _field
from typing import Iterable, Mapping, Optional

from lxml import etree

_NAME = r"[A-Za-z][A-Za-z0-9_ -]*?"
_PATTERN = re.compile(r"\{\{\{\{|\}\}\}\}|\{\{\s*(" + _NAME + r")\s*\}\}")
_PARAMETERS = "Parameters"

# What kinds of place there are, as written in the manifest and shown to the user.
KINDS = ("title", "text", "field-caption", "datasource-caption", "parameter-value")


def tokens_in(text: str) -> list[str]:
    """The token names in `text`, in order of appearance (escapes are not tokens)."""
    return [m.group(1) for m in _PATTERN.finditer(text or "") if m.group(1) is not None]


def has_syntax(text: str) -> bool:
    """True if `text` holds a token or an escape: a template with any such place declares its tokens."""
    return bool(_PATTERN.search(text or ""))


def render(text: str, values: Mapping[str, str]) -> str:
    """`text` with each token replaced by its value and each escape by the literal braces. A value is plain text and
    is not expanded again (`{{a}}` with `a = "{{b}}"` gives `{{b}}`). A name with no value raises `KeyError`."""
    def one(m):
        if m.group(1) is not None:
            return str(values[m.group(1)])
        return "{{" if m.group(0).startswith("{") else "}}"
    return _PATTERN.sub(one, text)


@dataclass
class Place:
    """One piece of text that can hold tokens, and everything that must change with it."""

    kind: str
    object: str                                            # the sheet, dashboard, field or parameter it belongs to
    targets: list = _field(default_factory=list)           # [(element, attribute or None for the text)]
    quoted: bool = False                                   # a Tableau string literal: "East", with "" for a quote

    def _raw(self) -> str:
        element, attr = self.targets[0]
        return (element.get(attr) if attr else element.text) or ""

    def text(self) -> str:
        raw = self._raw()
        if self.quoted and len(raw) >= 2 and raw[0] == raw[-1] == '"':
            return raw[1:-1].replace('""', '"')
        return raw

    def set(self, text: str) -> None:
        literal = '"' + text.replace('"', '""') + '"' if self.quoted else text
        for element, attr in self.targets:
            if attr:
                element.set(attr, literal)
            else:
                element.text = literal


def _name(el, *keys: str) -> str:
    for key in keys:
        if el.get(key):
            return el.get(key)
    return ""


def places(doc) -> list[Place]:
    """Every place in a workbook that can hold a token (whether or not it does)."""
    out: list[Place] = []
    for kind_xpath in (("/workbook/worksheets/worksheet", "./layout-options/title//run"),
                       ("/workbook/dashboards/dashboard", "./layout-options/title//run")):
        for sheet in doc.xpath(kind_xpath[0]):
            for run in sheet.xpath(kind_xpath[1]):
                out.append(Place("title", sheet.get("name", ""), [(run, None)]))
    for dash in doc.xpath("/workbook/dashboards/dashboard"):
        for run in dash.xpath(".//zone[@type-v2='text' or @type='text']//run"):
            out.append(Place("text", dash.get("name", ""), [(run, None)]))
    for ds in doc.xpath("/workbook/datasources/datasource[@name != $p]", p=_PARAMETERS):
        name = ds.get("name")
        if ds.get("caption") is not None:
            targets = [(ds, "caption")] + [(d, "caption") for d in doc.xpath(
                "//worksheet//datasources/datasource[@name=$n][@caption]", n=name)]
            out.append(Place("datasource-caption", _name(ds, "caption", "name"), targets))
        for col in ds.xpath("./column[@caption]"):
            targets = [(col, "caption")] + [(c, "caption") for c in doc.xpath(
                "//datasource-dependencies[@datasource=$d]/column[@name=$n][@caption]", d=name, n=col.get("name"))]
            out.append(Place("field-caption", f"{_name(ds, 'caption', 'name')}: {col.get('name')}", targets))
    for col in doc.xpath("/workbook/datasources/datasource[@name=$p]/column[@param-domain-type][@datatype='string']",
                         p=_PARAMETERS):
        label = col.get("caption") or col.get("name", "").strip("[]")
        if col.get("value") is not None:
            targets = [(col, "value")] + [(c, "formula") for c in col.xpath("./calculation[@formula]")]
            # the copies a worksheet keeps in its dependencies: the same value and the same mirrored formula
            for copy in doc.xpath("//datasource-dependencies[@datasource=$p]/column[@name=$n][@param-domain-type]",
                                  p=_PARAMETERS, n=col.get("name")):
                if copy.get("value") is not None:
                    targets.append((copy, "value"))
                targets += [(c, "formula") for c in copy.xpath("./calculation[@formula]")]
            out.append(Place("parameter-value", label, targets, quoted=True))
        for member in col.xpath("./members/member"):
            if member.get("value") is not None:
                out.append(Place("parameter-value", label, [(member, "value")], quoted=True))
            if member.get("alias") is not None:
                out.append(Place("parameter-value", label, [(member, "alias")]))
    return out


# characters XML 1.0 cannot hold (lxml refuses them): control characters other than tab, newline and return, the
# surrogates and U+FFFE / U+FFFF
_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def illegal_character(text: str) -> Optional[str]:
    """The first character of `text` that an XML document cannot hold, written as `U+000B`, or None."""
    m = _ILLEGAL.search(text)
    return f"U+{ord(m.group(0)):04X}" if m else None


def declared(doc) -> tuple[dict[str, list[dict]], bool]:
    """The tokens a workbook declares, `{name: [{"kind", "object"}, ...]}` in document order without repeats, and
    whether any place has token syntax at all (an escape alone makes a template process its text on apply)."""
    found: dict[str, list[dict]] = {}
    syntax = False
    for place in places(doc):
        text = place.text()
        if not has_syntax(text):
            continue
        syntax = True
        for name in dict.fromkeys(tokens_in(text)):
            where = {"kind": place.kind, "object": place.object}
            if where not in found.setdefault(name, []):
                found[name].append(where)
    return found, syntax


def expand(doc, values: Mapping[str, str]) -> int:
    """Replace the tokens and escapes in every place of `doc` in place; return how many places changed."""
    changed = 0
    for place in places(doc):
        text = place.text()
        if has_syntax(text):
            place.set(render(text, values))
            changed += 1
    return changed


def unfilled(doc, values: Mapping[str, str]) -> dict[str, list[dict]]:
    """The tokens of `doc` that `values` does not give, with every place each occurs in."""
    found, _ = declared(doc)
    return {name: where for name, where in found.items() if name not in values}


def formula_hits(doc) -> list[tuple[str, str]]:
    """Token-like text inside a calculation's formula, `(field or parameter, formula)`: never replaced. A
    parameter's own value mirrors into its calculation and is a place, not a hit."""
    hits = []
    for calc in doc.xpath("//column/calculation[@formula]"):
        col = calc.getparent()
        parent = col.getparent()
        if col.get("param-domain-type") and _PARAMETERS in (parent.get("name"), parent.get("datasource")):
            continue
        if tokens_in(calc.get("formula")):
            hits.append((col.get("caption") or col.get("name", ""), calc.get("formula")))
    return hits


def unscanned_hits(doc) -> list[tuple[str, str]]:
    """Tokens typed in text the feature does not scan, `(where, text)`: any text run that is not one of the places
    (a tooltip, an annotation, an axis title, a dashboard title zone, a worksheet caption). They stay as typed."""
    found = places(doc)    # kept alive: an lxml element is only the same object while something holds it
    covered = {el for place in found for el, attr in place.targets if attr is None}
    hits = []
    for run in doc.xpath("//run"):
        if run in covered or not tokens_in(run.text):
            continue
        owner = next((a for a in run.iterancestors() if a.tag in ("worksheet", "dashboard")), None)
        where = f"{owner.tag} {owner.get('name', '')}".strip() if owner is not None else "the workbook"
        hits.append((where, run.text))
    return hits


def broken_hits(doc) -> list[tuple[str, str, str]]:
    """Places whose text has a `{{` or `}}` that is not part of a whole token or an escape (a token cut in two by a
    change of format, a missing brace): `(kind, object, text)`."""
    hits = []
    for place in places(doc):
        text = _PATTERN.sub("", place.text())
        if "{{" in text or "}}" in text:
            hits.append((place.kind, place.object, place.text()))
    return hits
