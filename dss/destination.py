"""Independent comparison; preferences never silently become allocation constraints."""

from dataclasses import dataclass

from .admissibility import validate_eligibility
from .planning import PlanningScenario


@dataclass(frozen=True)
class DestinationComparison:
    asset_id: str
    pathway_id: str
    eligibility: str
    economic_value: float | None
    avoided_co2_kg: float | None
    rank: int | None
    preferred: bool
    criterion: str
    explanation: str


def compare(scenario: PlanningScenario, eligibility, criterion="economic_value"):
    if criterion not in {"economic_value", "avoided_co2_kg"}:
        raise ValueError("comparison criterion must be economic_value or avoided_co2_kg")
    records = validate_eligibility(scenario, eligibility)
    values = {(v.asset_id, v.pathway_id): v for v in scenario.values}
    rows = []
    for battery in scenario.batteries:
        options = [r for r in records if r.asset_id == battery.asset_id]
        eligible = [r for r in options if r.status == "eligible"]
        if any((r.asset_id, r.pathway_id) not in values for r in eligible):
            raise ValueError(f"missing assessment values for eligible options of {battery.asset_id}")
        scores = {r.pathway_id: getattr(values[(r.asset_id, r.pathway_id)], criterion) for r in eligible}
        for record in options:
            value = values.get((record.asset_id, record.pathway_id))
            rank = (1 + sum(score > scores[record.pathway_id] for score in scores.values())
                    if record.status == "eligible" else None)
            rows.append(DestinationComparison(
                record.asset_id, record.pathway_id, record.status,
                value.economic_value if value else None, value.avoided_co2_kg if value else None,
                rank, rank == 1, criterion,
                "Preference among currently eligible destinations; shared limits and deferral are not ranked."
                if rank is not None else "; ".join((*record.reasons, *[f"Missing {f}" for f in record.missing_fields])),
            ))
    return tuple(rows)
