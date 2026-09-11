"""twbparser_py: a native Python port of the twbparser R package.

Parses Tableau .twb/.twbx workbook files into pandas DataFrames. Ported
from https://github.com/PrigasG/twbparser (MIT licensed).
"""

from .calculated_fields import extract_calculated_fields, extract_raw_fields
from .dashboards import dashboard_sheets, list_dashboards
from .datasources import extract_datasource_details, extract_named_connections, extract_parameters
from .fields import extract_columns_with_table_source, infer_implicit_relationships
from .joins import extract_joins
from .parser import TwbParser
from .relationships import extract_relations, extract_relationships
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
    "extract_relations",
    "extract_relationships",
    "validate_relationships",
    "extract_twb_from_twbx",
    "twbx_extract_files",
    "twbx_list",
]

__version__ = "0.1.0"
