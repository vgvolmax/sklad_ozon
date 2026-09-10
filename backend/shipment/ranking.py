"""Pure deterministic operational ranking of Ozon validation evidence."""
from collections import defaultdict
from decimal import Decimal

from backend.ozon.draft_contracts import ValidationState
from .contracts import RankedShipmentOption, ShipmentOptionOutcome, ShipmentScenario

RANKABLE = {ValidationState.ACCEPTED, ValidationState.PARTIAL, ValidationState.NO_TIMESLOT}


def _operational_key(option: RankedShipmentOption) -> tuple[int, int, int, int, int]:
    return (
        0 if option.accepted_qty > 0 else 1,
        0 if option.has_timeslot else 1,
        -option.accepted_cluster_count,
        -option.accepted_qty,
        option.rejected_qty,
    )


def _handoff_preference_index(point_id: int, scenario: ShipmentScenario) -> int:
    try:
        return scenario.selected_handoff_point_ids.index(point_id)
    except ValueError:
        return len(scenario.selected_handoff_point_ids)


def _order_bucket(
    options: list[RankedShipmentOption], scenario: ShipmentScenario,
) -> tuple[RankedShipmentOption, ...]:
    """Reorder only handoff slots, leaving DIRECT at its stable baseline position."""
    baseline = sorted(options, key=lambda option: option.option_id)
    handoff_positions = [
        index for index, option in enumerate(baseline)
        if option.outcome.candidate.handoff_point_id is not None
    ]
    handoff_options = sorted(
        (baseline[index] for index in handoff_positions),
        key=lambda option: (
            _handoff_preference_index(
                option.outcome.candidate.handoff_point_id, scenario),
            option.option_id,
        ),
    )
    for index, option in zip(handoff_positions, handoff_options):
        baseline[index] = option
    return tuple(baseline)


def rank_outcomes(
    outcomes: tuple[ShipmentOptionOutcome, ...], scenario: ShipmentScenario,
) -> tuple[tuple[RankedShipmentOption, ...], tuple[ShipmentOptionOutcome, ...]]:
    buckets: dict[tuple[int, int, int, int, int], list[RankedShipmentOption]] = defaultdict(list)
    unavailable = []
    for outcome in outcomes:
        validation = outcome.validation
        accepted = validation.accepted_assignments
        if validation.state not in RANKABLE or not accepted:
            unavailable.append(outcome)
            continue
        accepted_qty = sum(row.quantity for row in accepted)
        rejected_qty = sum(row.quantity for row in validation.rejected_assignments)
        reasons = [
            "OZON_ACCEPTED_ASSIGNMENTS",
            "CURRENT_TIMESLOT_AVAILABLE" if validation.timeslots
            else "CURRENT_TIMESLOT_UNAVAILABLE",
        ]
        if validation.state is ValidationState.PARTIAL:
            reasons.append("OZON_PARTIAL_ACCEPTANCE")
        if outcome.candidate.handoff_point_id is not None:
            reasons.append("USER_HANDOFF_PREFERENCE")
        option = RankedShipmentOption(
            outcome.candidate.candidate_id,
            outcome,
            accepted_qty,
            rejected_qty,
            len({row.destination_cluster_id for row in accepted}),
            len({row.sku for row in accepted}),
            sum((row.total_volume_l for row in accepted), Decimal("0")),
            bool(validation.timeslots),
            tuple(reasons),
        )
        buckets[_operational_key(option)].append(option)

    ranked = tuple(
        option
        for key in sorted(buckets)
        for option in _order_bucket(buckets[key], scenario)
    )
    return ranked, tuple(unavailable)
