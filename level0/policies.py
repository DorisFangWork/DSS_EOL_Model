"""Deterministic Level 0 diagnostic and feasible baseline policies."""

from __future__ import annotations

from dataclasses import dataclass
from math import inf
from typing import Callable

from dss.allocation import AllocationAction, EvaluationReport

from .evaluation import evaluate_action
from .instance import StaticAllocationInstance


@dataclass(frozen=True, slots=True)
class PolicyOutcome:
    policy_name: str
    action: AllocationAction
    evaluation: EvaluationReport
    diagnostic_only: bool = False


def _payoff_or_defer(
    instance: StaticAllocationInstance, asset_id: str, pathway_id: str
) -> float:
    return instance.coefficients[(asset_id, pathway_id)].economic_value


def independent_best(instance: StaticAllocationInstance) -> AllocationAction:
    """Capacity-ignoring diagnostic upper bound, not generally implementable."""

    assignments: dict[str, str | None] = {}
    for asset in sorted(instance.assets, key=lambda item: item.asset_id):
        candidates = [
            coefficient
            for (asset_id, _), coefficient in instance.coefficients.items()
            if asset_id == asset.asset_id and coefficient.admissible
        ]
        candidates.sort(key=lambda item: (-item.economic_value, item.pathway_id))
        if candidates and candidates[0].economic_value >= -instance.deferral_costs[asset.asset_id]:
            assignments[asset.asset_id] = candidates[0].pathway_id
        else:
            assignments[asset.asset_id] = None
    return AllocationAction(assignments)


class _CapacityLedger:
    def __init__(self, instance: StaticAllocationInstance) -> None:
        self.pathway_remaining = {
            pathway.pathway_id: inf if pathway.capacity is None else pathway.capacity
            for pathway in instance.pathways
        }
        self.resource_remaining = {
            resource.resource_id: resource.capacity for resource in instance.resources
        }

    def can_take(self, coefficient, tolerance: float = 1e-9) -> bool:
        if coefficient.pathway_capacity_use > self.pathway_remaining[coefficient.pathway_id] + tolerance:
            return False
        return all(
            use <= self.resource_remaining[resource_id] + tolerance
            for resource_id, use in coefficient.resource_use.items()
        )

    def take(self, coefficient) -> None:
        self.pathway_remaining[coefficient.pathway_id] -= coefficient.pathway_capacity_use
        for resource_id, use in coefficient.resource_use.items():
            self.resource_remaining[resource_id] -= use


def greedy_value(instance: StaticAllocationInstance) -> AllocationAction:
    """Assign the largest current asset-pathway values first when feasible."""

    ledger = _CapacityLedger(instance)
    assignments: dict[str, str | None] = {}
    candidates = sorted(
        (coefficient for coefficient in instance.coefficients.values() if coefficient.admissible),
        key=lambda item: (-item.economic_value, item.asset_id, item.pathway_id),
    )
    for coefficient in candidates:
        if coefficient.asset_id in assignments:
            continue
        if coefficient.economic_value < -instance.deferral_costs[coefficient.asset_id]:
            continue
        if ledger.can_take(coefficient):
            assignments[coefficient.asset_id] = coefficient.pathway_id
            ledger.take(coefficient)
    for asset in instance.assets:
        assignments.setdefault(asset.asset_id, None)
    return AllocationAction(assignments)


def soh_threshold(
    instance: StaticAllocationInstance,
    *,
    threshold: float = 0.75,
    preferred_pathway: str = "repurpose",
) -> AllocationAction:
    """Operational rule: highest-SOH eligible packs receive preferred capacity."""

    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be in [0, 1]")
    if preferred_pathway not in instance.pathway_by_id:
        raise KeyError(preferred_pathway)
    ledger = _CapacityLedger(instance)
    assignments: dict[str, str | None] = {}
    ranked = sorted(instance.assets, key=lambda a: (-a.soh, -a.usable_kwh, a.asset_id))
    for asset in ranked:
        coefficient = instance.coefficients[(asset.asset_id, preferred_pathway)]
        if asset.soh >= threshold and coefficient.admissible and ledger.can_take(coefficient):
            assignments[asset.asset_id] = preferred_pathway
            ledger.take(coefficient)

    for asset in sorted(instance.assets, key=lambda a: a.asset_id):
        if asset.asset_id in assignments:
            continue
        alternatives = sorted(
            (
                coefficient
                for (asset_id, pathway_id), coefficient in instance.coefficients.items()
                if asset_id == asset.asset_id
                and pathway_id != preferred_pathway
                and coefficient.admissible
            ),
            key=lambda item: (-item.economic_value, item.pathway_id),
        )
        selected = next(
            (
                coefficient
                for coefficient in alternatives
                if coefficient.economic_value >= -instance.deferral_costs[asset.asset_id]
                and ledger.can_take(coefficient)
            ),
            None,
        )
        if selected is None:
            assignments[asset.asset_id] = None
        else:
            assignments[asset.asset_id] = selected.pathway_id
            ledger.take(selected)
    return AllocationAction(assignments)


def fifo(instance: StaticAllocationInstance) -> AllocationAction:
    """Oldest-held assets first, then best feasible current pathway."""

    ledger = _CapacityLedger(instance)
    assignments: dict[str, str | None] = {}
    for asset in sorted(instance.assets, key=lambda a: (-a.periods_held, a.asset_id)):
        candidates = sorted(
            (
                coefficient
                for (asset_id, _), coefficient in instance.coefficients.items()
                if asset_id == asset.asset_id and coefficient.admissible
            ),
            key=lambda item: (-item.economic_value, item.pathway_id),
        )
        selected = next(
            (
                coefficient
                for coefficient in candidates
                if coefficient.economic_value >= -instance.deferral_costs[asset.asset_id]
                and ledger.can_take(coefficient)
            ),
            None,
        )
        if selected is None:
            assignments[asset.asset_id] = None
        else:
            assignments[asset.asset_id] = selected.pathway_id
            ledger.take(selected)
    return AllocationAction(assignments)


PolicyFunction = Callable[[StaticAllocationInstance], AllocationAction]


def run_policy(
    instance: StaticAllocationInstance,
    name: str,
    policy: PolicyFunction,
    *,
    diagnostic_only: bool = False,
) -> PolicyOutcome:
    action = policy(instance)
    return PolicyOutcome(
        policy_name=name,
        action=action,
        evaluation=evaluate_action(instance, action),
        diagnostic_only=diagnostic_only,
    )


def policy_gap_percent(reference: float, candidate: float, *, tolerance: float = 1e-9) -> float | None:
    if abs(reference) <= tolerance:
        return None
    return 100.0 * (reference - candidate) / abs(reference)

