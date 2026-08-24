"""The single authoritative, solver-independent Level 0 evaluator."""

from __future__ import annotations

from collections import defaultdict

from dss.allocation import AllocationAction, EvaluationReport

from .instance import StaticAllocationInstance


def evaluate_action(
    instance: StaticAllocationInstance,
    action: AllocationAction,
    *,
    tolerance: float = 1e-7,
) -> EvaluationReport:
    asset_ids = set(instance.asset_by_id)
    pathway_ids = set(instance.pathway_by_id)
    declared_ids = set(action.assignments)
    violations: list[str] = []

    missing = sorted(asset_ids - declared_ids)
    extra = sorted(declared_ids - asset_ids)
    if missing:
        violations.append(f"missing actions for assets: {missing}")
    if extra:
        violations.append(f"actions supplied for unknown assets: {extra}")

    gross_value = 0.0
    deferral_cost = 0.0
    avoided_co2_kg = 0.0
    pathway_use: defaultdict[str, float] = defaultdict(float)
    resource_use: defaultdict[str, float] = defaultdict(float)
    pathway_counts: defaultdict[str, int] = defaultdict(int)

    for asset_id in sorted(asset_ids & declared_ids):
        pathway_id = action.assignments[asset_id]
        if pathway_id is None:
            deferral_cost += instance.deferral_costs[asset_id]
            continue
        if pathway_id not in pathway_ids:
            violations.append(f"asset {asset_id} uses unknown pathway {pathway_id}")
            continue
        coefficient = instance.coefficients[(asset_id, pathway_id)]
        if not coefficient.admissible:
            violations.append(f"asset {asset_id} is inadmissible for {pathway_id}")
        gross_value += coefficient.economic_value
        avoided_co2_kg += coefficient.avoided_co2_kg
        pathway_use[pathway_id] += coefficient.pathway_capacity_use
        pathway_counts[pathway_id] += 1
        for resource_id, use in coefficient.resource_use.items():
            resource_use[resource_id] += use

    for pathway in instance.pathways:
        use = pathway_use[pathway.pathway_id]
        if pathway.capacity is not None and use > pathway.capacity + tolerance:
            violations.append(
                f"pathway {pathway.pathway_id} use {use:.9g} exceeds capacity "
                f"{pathway.capacity:.9g}"
            )
    for resource in instance.resources:
        use = resource_use[resource.resource_id]
        if use > resource.capacity + tolerance:
            violations.append(
                f"resource {resource.resource_id} use {use:.9g} exceeds capacity "
                f"{resource.capacity:.9g}"
            )
    if (
        instance.co2_floor_kg is not None
        and avoided_co2_kg + tolerance < instance.co2_floor_kg
    ):
        violations.append(
            f"avoided CO2 {avoided_co2_kg:.9g} is below floor {instance.co2_floor_kg:.9g}"
        )

    normalized_pathway_use = {
        pathway.pathway_id: float(pathway_use[pathway.pathway_id])
        for pathway in instance.pathways
    }
    normalized_resource_use = {
        resource.resource_id: float(resource_use[resource.resource_id])
        for resource in instance.resources
    }
    return EvaluationReport(
        feasible=not violations,
        economic_objective=gross_value - deferral_cost,
        gross_pathway_value=gross_value,
        deferral_cost=deferral_cost,
        avoided_co2_kg=avoided_co2_kg,
        pathway_use=normalized_pathway_use,
        resource_use=normalized_resource_use,
        violations=tuple(violations),
        details={
            "pathway_counts": {
                pathway.pathway_id: pathway_counts[pathway.pathway_id]
                for pathway in instance.pathways
            },
            "deferred_count": sum(value is None for value in action.assignments.values()),
        },
    )

