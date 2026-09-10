"""Harmless source-text cleanup and explicit cluster resolution."""

import re
import unicodedata
from collections.abc import Mapping
from math import isfinite

from backend.domain.contracts import ImportDiagnostic

_WHITESPACE = re.compile(r"\s+")


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFC", str(value)).replace("\ufeff", "").replace("\u00a0", " ")
    return _WHITESPACE.sub(" ", text).strip()


def normalize_seller_article_identity(value: object) -> str:
    """Preserve string identity while canonicalizing integer-like numeric cells."""
    if isinstance(value, bool):
        return normalize_text(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and isfinite(value) and value.is_integer():
        return str(int(value))
    return normalize_text(value)


def normalize_header(value: object) -> str:
    return normalize_text(value).casefold()


def normalize_cluster_label(raw: object) -> str:
    return normalize_text(raw)


def _normalized_map(values: Mapping[str, str]) -> dict[str, str]:
    return {normalize_cluster_label(key).casefold(): value for key, value in values.items()}


def resolve_cluster_id(raw_label: object, alias_map: Mapping[str, str], manual_mappings: Mapping[str, str]):
    label = normalize_cluster_label(raw_label)
    key = label.casefold()
    if key in (manual := _normalized_map(manual_mappings)):
        return manual[key], None
    if key in (aliases := _normalized_map(alias_map)):
        return aliases[key], None
    return None, ImportDiagnostic(
        severity="warning", code="UNRESOLVED_CLUSTER",
        message=f"Cluster label is not present in explicit mappings: {label!r}", field="cluster",
    )
