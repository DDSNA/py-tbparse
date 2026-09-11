"""twbparser_py: a native Python port of the twbparser R package.

Parses Tableau .twb/.twbx workbook files into pandas DataFrames. Ported
from https://github.com/PrigasG/twbparser (MIT licensed).
"""

from .calculated_fields import extract_calculated_fields, extract_raw_fields
from .dashboards import dashboard_sheets, list_dashboards
from .datasources import extract_datasource_details, extract_named_connections, extract_parameters
from .fields import extract_columns_with_table_source, infer_implicit_relationships
from .graph import to_dot
from .joins import extract_joins
from .parser import TwbParser
from .published import extract_published_refs
from .relationships import extract_relations, extract_relationships
from .sql import extract_custom_sql, extract_initial_sql
from .validators import validate_relationships
from ._xml import extract_twb_from_twbx, twbx_extract_files, twbx_list

__all__ = [
    "TwbParser",
    "extract_calculated_fields",
    "extract_raw_fields",
    "dashboard_sheets",
    "list_dashboards",
    "extract_datasource_details",
    "extract_named_connections",
    "extract_parameters",
    "extract_columns_with_table_source",
    "infer_implicit_relationships",
    "extract_joins",
    "to_dot",
    "extract_relations",
    "extract_relationships",
    "extract_custom_sql",
    "extract_initial_sql",
    "extract_published_refs",
    "validate_relationships",
    "extract_twb_from_twbx",
    "twbx_extract_files",
    "twbx_list",
]

try:
    from importlib.metadata import PackageNotFoundError, version

    __version__ = version("twbparser-py")
except PackageNotFoundError:  # pragma: no cover - not installed, e.g. running from source
    __version__ = "0.0.0+unknown"
