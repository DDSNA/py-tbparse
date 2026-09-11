"""Name-cleaning helpers, ported from twbparser's R/utils.R."""

from __future__ import annotations

import re
from typing import Optional

_TRAILING_HEX32 = re.compile(r"_[0-9A-Fa-f]{32}$")
_LEADING_BRACKET_PREFIX = re.compile(r"^\[.*?\]\.")
_BRACKETS = re.compile(r"[\[\]]")
_DERIVATION_WRAPPER = re.compile(r"^[a-z]+:(.+):[a-z]{1,3}$")


def clean_table(x: Optional[str]) -> Optional[str]:
    """Port of `.twb_clean_table`.

    Drops `[Extract].`/`[Connection].` prefixes, strips `[]`, and removes
    Tableau's trailing 32-char hex suffix.
    """
    if x is None:
        return None
    s = str(x)
    s = _LEADING_BRACKET_PREFIX.sub("", s)
    s = _BRACKETS.sub("", s)
    s = _TRAILING_HEX32.sub("", s)
    s = s.strip()
    return s if s else None


def clean_field(x: Optional[str]) -> Optional[str]:
    """Port of `.twb_clean_field`.

    Strips `[]`, takes the last dot-separated token, then unwraps a
    Tableau column-instance wrapper like `none:Category:nk` -> `Category`.
    """
    if x is None:
        return None
    s = str(x)
    s = _BRACKETS.sub("", s)

    parts = [p for p in s.split(".") if p]
    token = parts[-1] if parts else None
    if token is None:
        return None

    m = _DERIVATION_WRAPPER.match(token)
    if m:
        return m.group(1)
    return token


def attr_safe_get(attrs: dict, name: str, default=None):
    """Port of `attr_safe_get`."""
    if attrs is None:
        return default
    return attrs.get(name, default)


def strip_brackets(x: Optional[str]) -> Optional[str]:
    """Port of `.strip_brackets`."""
    if x is None:
        return None
    return _BRACKETS.sub("", x)


def basename_safe(x: Optional[str], fallback: str = "<unknown>") -> str:
    """Port of `basename_safe`."""
    if not x:
        return fallback
    import os

    return os.path.basename(x)
