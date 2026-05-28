"""Field references for PBIR visual data bindings.

Helpers per costruire le strutture JSON nested che Power BI usa per
referenziare measures, columns, aggregazioni.

Portato verbatim da ADE 2026-05-24 (puri helpers, no gotchas).
"""
from __future__ import annotations


def measure(entity: str, property: str) -> dict:
    """Reference a DAX measure.

    Args:
        entity: Table name (e.g. ``"FactSales"``).
        property: Measure name (e.g. ``"Total Revenue"``).
    """
    return {
        "_type": "measure",
        "entity": entity,
        "property": property,
    }


def column(entity: str, property: str, display_name: str | None = None) -> dict:
    """Reference a table column.

    Args:
        entity: Table name (e.g. ``"DimProduct"``).
        property: Column name (e.g. ``"Category"``).
        display_name: Optional display name override.
    """
    return {
        "_type": "column",
        "entity": entity,
        "property": property,
        "display_name": display_name,
    }


def aggregation(
    entity: str,
    property: str,
    function: int = 0,
    display_name: str | None = None,
) -> dict:
    """Reference an aggregated column.

    Args:
        entity: Table name.
        property: Column name.
        function: Aggregation type (0=Sum, 1=Avg, 2=Min, 3=Max, 4=Count, 5=CountDistinct).
        display_name: Optional display name.
    """
    return {
        "_type": "aggregation",
        "entity": entity,
        "property": property,
        "function": function,
        "display_name": display_name,
    }


SUM = 0
AVG = 1
MIN = 2
MAX = 3
COUNT = 4
COUNT_DISTINCT = 5


def _build_field_expr(field_def: dict) -> dict:
    """Convert a field definition to PBIR query expression."""
    source_ref = {"Entity": field_def["entity"]}

    if field_def["_type"] == "measure":
        return {
            "Measure": {
                "Expression": {"SourceRef": source_ref},
                "Property": field_def["property"],
            }
        }
    if field_def["_type"] == "column":
        return {
            "Column": {
                "Expression": {"SourceRef": source_ref},
                "Property": field_def["property"],
            }
        }
    if field_def["_type"] == "aggregation":
        return {
            "Aggregation": {
                "Expression": {
                    "Column": {
                        "Expression": {"SourceRef": source_ref},
                        "Property": field_def["property"],
                    }
                },
                "Function": field_def["function"],
            }
        }
    raise ValueError(f"Unknown field type: {field_def['_type']}")


def _build_query_ref(field_def: dict) -> str:
    """Build the queryRef string for a field."""
    if field_def["_type"] in ("measure", "column"):
        return f"{field_def['entity']}.{field_def['property']}"
    if field_def["_type"] == "aggregation":
        func_names = {0: "Sum", 1: "Avg", 2: "Min", 3: "Max", 4: "Count", 5: "CountDistinct"}
        func_name = func_names.get(field_def["function"], "Sum")
        return f"{func_name}({field_def['entity']}.{field_def['property']})"
    return ""


def _build_native_query_ref(field_def: dict) -> str:
    """Build the nativeQueryRef (display name) for a field."""
    return field_def.get("display_name") or field_def["property"]


def _build_projection(field_def: dict, active: bool = False) -> dict:
    """Build a complete projection entry for a query state role."""
    proj = {
        "field": _build_field_expr(field_def),
        "queryRef": _build_query_ref(field_def),
        "nativeQueryRef": _build_native_query_ref(field_def),
    }
    if active:
        proj["active"] = True
    if field_def.get("display_name"):
        proj["displayName"] = field_def["display_name"]
    return proj
