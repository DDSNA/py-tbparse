"""py_tbparse: a native Python port of the twbparser R package.

Parses Tableau .twb/.twbx workbook files into pandas DataFrames. Ported
from https://github.com/PrigasG/twbparser (MIT licensed).
"""

from .batch import scan_folder
from .calculated_fields import extract_calculated_fields, extract_raw_fields
from .dashboards import dashboard_sheets, list_dashboards
from .datasources import extract_datasource_details, extract_named_connections, extract_parameters
from .diff import diff_tables, diff_workbooks
from .fields import extract_columns_with_table_source, infer_implicit_relationships
from .graph import graph_data, to_dot
from .joins import extract_joins
from .library import (
    LibraryError,
    build_imported_workbook,
    export_library,
    import_library,
    library_table,
    load_library,
    plan_import,
    save_library,
)
from .parser import TwbParser
from .published import extract_published_refs
from .relationships import extract_relations, extract_relationships
from .rename import (
    apply_field_renames,
    compare_field_schemas,
    load_rename_mapping,
    normalize_name,
    suggest_field_renames,
    suggest_renames,
)
from .sql import extract_custom_sql, extract_initial_sql
from .templates import (
    Template,
    TemplateError,
    apply_template,
    broken_sheets,
    check_data,
    explain,
    load_answers,
    load_mapping,
    load_template,
    make_template,
    read_data,
    resolve_apply,
    suggest_mapping,
)
from .template_batch import apply_template_folder
from .workbook_audit import audit
from .docgen import template_markdown, workbook_markdown
from .findings import format_findings, run_rules
from .template_check import check_template
from .template_update import diff_template_revisions, template_update_report, update_from_answers
from .usage import field_usage
from .validators import validate_relationships
from .verify import validate_workbook
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
    "graph_data",
    "extract_relations",
    "extract_relationships",
    "extract_custom_sql",
    "extract_initial_sql",
    "extract_published_refs",
    "validate_relationships",
    "validate_workbook",
    "extract_twb_from_twbx",
    "twbx_extract_files",
    "twbx_list",
    "diff_tables",
    "diff_workbooks",
    "scan_folder",
    "apply_field_renames",
    "compare_field_schemas",
    "load_rename_mapping",
    "normalize_name",
    "suggest_field_renames",
    "suggest_renames",
    "field_usage",
    "Template",
    "TemplateError",
    "make_template",
    "load_template",
    "read_data",
    "suggest_mapping",
    "load_mapping",
    "apply_template",
    "apply_template_folder",
    "diff_template_revisions",
    "template_update_report",
    "update_from_answers",
    "check_template",
    "template_markdown",
    "workbook_markdown",
    "audit",
    "run_rules",
    "format_findings",
    "resolve_apply",
    "load_answers",
    "broken_sheets",
    "check_data",
    "explain",
    "LibraryError",
    "export_library",
    "save_library",
    "load_library",
    "library_table",
    "plan_import",
    "build_imported_workbook",
    "import_library",
]

try:
    from importlib.metadata import PackageNotFoundError, version

    __version__ = version("py-tbparse")
except PackageNotFoundError:  # pragma: no cover - not installed, e.g. running from source
    __version__ = "0.0.0+unknown"
