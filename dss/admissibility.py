"""Destination-specific admission with explicit unresolved information."""

from dataclasses import dataclass

from .domain import PathwaySpec
from .planning import BatteryRecord, PlanningScenario


@dataclass(frozen=True)
class Eligibility:
    asset_id: str
    pathway_id: str
    status: str
    reasons: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    source: str = "configured-entry-rules/v1"

    def __post_init__(self):
        if self.status not in {"eligible", "ineligible", "undetermined"}:
            raise ValueError("unknown eligibility status")
        if not self.asset_id or not self.pathway_id or not self.source.strip():
            raise ValueError("eligibility needs identifiers and a source")
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "missing_fields", tuple(self.missing_fields))
        if self.status == "eligible" and (self.missing_fields or self.reasons):
            raise ValueError("eligible records cannot contain unmet or unresolved requirements")
        if self.status != "eligible" and not (self.reasons or self.missing_fields):
            raise ValueError("ineligible/undetermined records need an explanation")


def assess(battery: BatteryRecord, destination: PathwaySpec) -> Eligibility:
    failed, missing = [], []
    checks = (
        ("soh", destination.min_soh, lambda value, rule: value >= rule, "SOH is below the minimum"),
        ("safety_class", destination.max_safety_class, lambda value, rule: value <= rule, "Safety class exceeds the maximum"),
        ("chemistry", destination.allowed_chemistries, lambda value, rule: value in rule, "Chemistry is not accepted"),
    )
    for field, rule, passes, explanation in checks:
        if rule is None:
            continue
        value = getattr(battery, field)
        if value is None:
            missing.append(field)
        elif not passes(value, rule):
            failed.append(f"{explanation}: observed={value}, requirement={rule}")
    status = "ineligible" if failed else "undetermined" if missing else "eligible"
    return Eligibility(battery.asset_id, destination.pathway_id, status, tuple(failed), tuple(missing))


def assess_scenario(scenario: PlanningScenario) -> tuple[Eligibility, ...]:
    return tuple(assess(b, d) for b in scenario.batteries for d in scenario.destinations)


def validate_eligibility(scenario: PlanningScenario, records) -> tuple[Eligibility, ...]:
    records = tuple(records)
    keys = [(r.asset_id, r.pathway_id) for r in records]
    expected = {(b.asset_id, d.pathway_id) for b in scenario.batteries for d in scenario.destinations}
    if len(keys) != len(set(keys)) or set(keys) != expected:
        raise ValueError("eligibility must contain exactly one record for every battery/destination pair")
    return records
