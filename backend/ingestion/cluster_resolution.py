"""Deterministic, fail-closed cluster identity resolution before analytics."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from backend.domain.contracts import ImportDiagnostic, OrderRecord, TariffRow
from backend.ingestion.availability import AvailabilityRecord
from backend.ingestion.normalization import normalize_cluster_label, resolve_cluster_id
from backend.ingestion.restrictions import RestrictionRecord


@dataclass(frozen=True, slots=True)
class ClusterResolutionResult:
    availability: tuple[AvailabilityRecord, ...]
    restrictions: tuple[RestrictionRecord, ...]
    orders: tuple[OrderRecord, ...]
    tariffs: tuple[TariffRow, ...]
    diagnostics: tuple[ImportDiagnostic, ...]


def resolve_analysis_clusters(
    availability: Iterable[AvailabilityRecord],
    restrictions: Iterable[RestrictionRecord],
    orders: Iterable[OrderRecord],
    tariffs: Iterable[TariffRow],
    manual_mappings: Mapping[str, str],
) -> ClusterResolutionResult:
    """Resolve only exact normalized labels or explicit aliases to tariff labels."""
    normalized_tariffs = tuple(
        replace(row,
                origin_cluster_id=normalize_cluster_label(row.origin_cluster_id),
                destination_cluster_id=normalize_cluster_label(row.destination_cluster_id))
        for row in tariffs
    )
    aliases: dict[str, str] = {}
    for row in normalized_tariffs:
        for label in (row.origin_cluster_id, row.destination_cluster_id):
            aliases.setdefault(label, label)

    diagnostics: list[ImportDiagnostic] = []
    valid_manual: dict[str, str] = {}
    canonical_keys = {label.casefold(): label for label in aliases}
    for source, target in manual_mappings.items():
        normalized_target = normalize_cluster_label(target)
        canonical = canonical_keys.get(normalized_target.casefold())
        if canonical is None:
            diagnostics.append(ImportDiagnostic(
                "error", "INVALID_MANUAL_CLUSTER_TARGET",
                f"Manual cluster target is absent from tariffs: {normalized_target!r}",
                field="manual_mappings",
            ))
        else:
            valid_manual[source] = canonical

    def resolved(label: object, source_type: str, field: str):
        value, diagnostic = resolve_cluster_id(label, aliases, valid_manual)
        if diagnostic is not None:
            diagnostics.append(replace(
                diagnostic, severity="error", field=field,
                message=(f"{source_type}.{field} is unresolved after exact cluster matching: "
                         f"{normalize_cluster_label(label)!r}"),
            ))
        return value

    resolved_availability = []
    for record in availability:
        cluster = resolved(record.cluster, "availability", "cluster")
        if cluster is not None:
            resolved_availability.append(replace(record, cluster=cluster))

    resolved_restrictions = []
    for record in restrictions:
        if not normalize_cluster_label(record.cluster):
            resolved_restrictions.append(record)
            continue
        cluster = resolved(record.cluster, "restrictions", "cluster")
        if cluster is not None:
            resolved_restrictions.append(replace(record, cluster=cluster))

    resolved_orders = []
    for record in orders:
        origin = resolved(record.origin_cluster, "orders", "origin_cluster")
        destination = resolved(record.destination_cluster, "orders", "destination_cluster")
        if origin is not None and destination is not None:
            resolved_orders.append(replace(record, origin_cluster=origin, destination_cluster=destination))

    return ClusterResolutionResult(
        tuple(resolved_availability), tuple(resolved_restrictions), tuple(resolved_orders),
        normalized_tariffs, tuple(diagnostics),
    )
