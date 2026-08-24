"""Cohort sufficiency checks, aggregated solve, lifting, and measured loss."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import floor
from types import MappingProxyType
from typing import Mapping

import pulp

from dss.allocation import AllocationAction, EvaluationReport
from dss.domain import Asset

from .evaluation import evaluate_action
from .instance import StaticAllocationInstance
from .model import make_cbc_solver, solve_milp


@dataclass(frozen=True, slots=True)
class CohortScheme:
    soh_band_width: float | None
    group_by_chemistry: bool = True
    group_by_safety: bool = True
    include_asset_id: bool = False

    def __post_init__(self) -> None:
        if self.soh_band_width is not None and not 0 < self.soh_band_width <= 1:
            raise ValueError("soh_band_width must be in (0, 1] or None")


@dataclass(frozen=True, slots=True)
class SufficiencyIssue:
    cohort_id: str
    pathway_id: str
    issue_type: str
    magnitude: float | None
    tolerance: float | None


@dataclass(frozen=True, slots=True)
class SufficiencyReport:
    sufficient: bool
    cohort_count: int
    issues: tuple[SufficiencyIssue, ...]


@dataclass(frozen=True, slots=True)
class CohortSolveResult:
    status: str
    scheme: CohortScheme
    group_count: int
    sufficient: bool
    representative_objective: float | None
    lifted_action: AllocationAction | None
    lifted_evaluation: EvaluationReport | None
    asset_optimal_objective: float | None
    representative_gap: float | None
    lifted_gap: float | None
    lifted_gap_percent: float | None
    cohort_pathway_counts: Mapping[tuple[str, str | None], int]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "cohort_pathway_counts", MappingProxyType(dict(self.cohort_pathway_counts))
        )


def _exact_solve_status(problem: pulp.LpProblem) -> str:
    """Normalize PuLP's model and solution certificates for exact cohort solves."""

    model_status = pulp.LpStatus.get(problem.status, f"Unknown({problem.status})")
    solution_status = int(getattr(problem, "sol_status", pulp.LpSolutionNoSolutionFound))
    if problem.status == pulp.LpStatusOptimal and solution_status == pulp.LpSolutionOptimal:
        return "Optimal"
    if solution_status == pulp.LpSolutionIntegerFeasible:
        return "FeasibleNotProvenOptimal"
    if model_status == "Optimal":
        return "NoExactCertificate"
    return model_status


def _cohort_key(asset: Asset, scheme: CohortScheme) -> tuple[object, ...]:
    parts: list[object] = []
    if scheme.include_asset_id:
        parts.append(asset.asset_id)
    if scheme.group_by_chemistry:
        parts.append(asset.chemistry)
    if scheme.group_by_safety:
        parts.append(asset.safety_class)
    if scheme.soh_band_width is not None:
        index = floor((asset.soh + 1e-12) / scheme.soh_band_width)
        parts.append(index)
    if not parts:
        parts.append("all")
    return tuple(parts)


def build_cohorts(
    instance: StaticAllocationInstance, scheme: CohortScheme
) -> Mapping[str, tuple[Asset, ...]]:
    grouped: defaultdict[tuple[object, ...], list[Asset]] = defaultdict(list)
    for asset in instance.assets:
        grouped[_cohort_key(asset, scheme)].append(asset)
    result: dict[str, tuple[Asset, ...]] = {}
    for index, key in enumerate(sorted(grouped, key=repr)):
        result[f"C{index:04d}:{repr(key)}"] = tuple(
            sorted(grouped[key], key=lambda asset: asset.asset_id)
        )
    return MappingProxyType(result)


def check_sufficiency(
    instance: StaticAllocationInstance,
    scheme: CohortScheme,
    *,
    value_tolerance: float = 1e-6,
    emissions_tolerance: float = 1e-6,
    deferral_tolerance: float = 1e-6,
    capacity_tolerance: float = 1e-9,
    resource_tolerance: float = 1e-9,
) -> SufficiencyReport:
    cohorts = build_cohorts(instance, scheme)
    issues: list[SufficiencyIssue] = []
    for cohort_id, assets in cohorts.items():
        deferral_spread = max(instance.deferral_costs[a.asset_id] for a in assets) - min(
            instance.deferral_costs[a.asset_id] for a in assets
        )
        if deferral_spread > deferral_tolerance:
            issues.append(
                SufficiencyIssue(
                    cohort_id,
                    "defer",
                    "deferral_cost",
                    deferral_spread,
                    deferral_tolerance,
                )
            )
        for pathway in instance.pathways:
            coefficients = [
                instance.coefficients[(asset.asset_id, pathway.pathway_id)] for asset in assets
            ]
            admissible_values = {coefficient.admissible for coefficient in coefficients}
            if len(admissible_values) > 1:
                issues.append(
                    SufficiencyIssue(cohort_id, pathway.pathway_id, "admissibility", None, None)
                )
                continue
            if not coefficients[0].admissible:
                continue
            value_spread = max(c.economic_value for c in coefficients) - min(
                c.economic_value for c in coefficients
            )
            if value_spread > value_tolerance:
                issues.append(
                    SufficiencyIssue(
                        cohort_id,
                        pathway.pathway_id,
                        "economic_value",
                        value_spread,
                        value_tolerance,
                    )
                )
            emissions_spread = max(c.avoided_co2_kg for c in coefficients) - min(
                c.avoided_co2_kg for c in coefficients
            )
            if emissions_spread > emissions_tolerance:
                issues.append(
                    SufficiencyIssue(
                        cohort_id,
                        pathway.pathway_id,
                        "avoided_co2",
                        emissions_spread,
                        emissions_tolerance,
                    )
                )
            capacity_spread = max(c.pathway_capacity_use for c in coefficients) - min(
                c.pathway_capacity_use for c in coefficients
            )
            if capacity_spread > capacity_tolerance:
                issues.append(
                    SufficiencyIssue(
                        cohort_id,
                        pathway.pathway_id,
                        "pathway_capacity_use",
                        capacity_spread,
                        capacity_tolerance,
                    )
                )
            all_resources = set().union(*(set(c.resource_use) for c in coefficients))
            for resource_id in all_resources:
                spread = max(c.resource_use.get(resource_id, 0.0) for c in coefficients) - min(
                    c.resource_use.get(resource_id, 0.0) for c in coefficients
                )
                if spread > resource_tolerance:
                    issues.append(
                        SufficiencyIssue(
                            cohort_id,
                            pathway.pathway_id,
                            f"resource_use:{resource_id}",
                            spread,
                            resource_tolerance,
                        )
                    )
    return SufficiencyReport(not issues, len(cohorts), tuple(issues))


def _representative_coefficients(
    instance: StaticAllocationInstance,
    assets: tuple[Asset, ...],
    pathway_id: str,
) -> tuple[bool, float, float, float, dict[str, float]]:
    coefficients = [instance.coefficients[(asset.asset_id, pathway_id)] for asset in assets]
    admissible = all(coefficient.admissible for coefficient in coefficients)
    economic = sum(coefficient.economic_value for coefficient in coefficients) / len(coefficients)
    emissions = sum(coefficient.avoided_co2_kg for coefficient in coefficients) / len(coefficients)
    pathway_use = max(coefficient.pathway_capacity_use for coefficient in coefficients)
    resource_ids = set().union(*(set(coefficient.resource_use) for coefficient in coefficients))
    resource_use = {
        resource_id: max(coefficient.resource_use.get(resource_id, 0.0) for coefficient in coefficients)
        for resource_id in resource_ids
    }
    return admissible, economic, emissions, pathway_use, resource_use


def solve_aggregated(
    instance: StaticAllocationInstance,
    scheme: CohortScheme,
    *,
    allow_lossy: bool = False,
) -> CohortSolveResult:
    sufficiency = check_sufficiency(instance, scheme)
    if not sufficiency.sufficient and not allow_lossy:
        raise ValueError("cohort scheme is insufficient; pass allow_lossy=True to measure its error")
    cohorts = build_cohorts(instance, scheme)
    problem = pulp.LpProblem("level0_cohort", pulp.LpMaximize)
    variables: dict[tuple[str, str | None], pulp.LpVariable] = {}
    representatives: dict[tuple[str, str], tuple[bool, float, float, float, dict[str, float]]] = {}
    for cohort_index, (cohort_id, assets) in enumerate(cohorts.items()):
        for pathway_index, pathway in enumerate(instance.pathways):
            representative = _representative_coefficients(
                instance, assets, pathway.pathway_id
            )
            representatives[(cohort_id, pathway.pathway_id)] = representative
            if representative[0]:
                variables[(cohort_id, pathway.pathway_id)] = problem.add_variable(
                    f"y_{cohort_index}_{pathway_index}",
                    lowBound=0,
                    upBound=len(assets),
                    cat=pulp.LpInteger,
                )
        variables[(cohort_id, None)] = problem.add_variable(
            f"yd_{cohort_index}", lowBound=0, upBound=len(assets), cat=pulp.LpInteger
        )

    problem += pulp.lpSum(
        representatives[(cohort_id, pathway_id)][1] * variable
        if pathway_id is not None
        else -sum(instance.deferral_costs[a.asset_id] for a in cohorts[cohort_id])
        / len(cohorts[cohort_id])
        * variable
        for (cohort_id, pathway_id), variable in variables.items()
    )
    for index, (cohort_id, assets) in enumerate(cohorts.items()):
        problem += (
            pulp.lpSum(
                variable
                for (candidate_id, _), variable in variables.items()
                if candidate_id == cohort_id
            )
            == len(assets),
            f"cohort_count_{index}",
        )
    for index, pathway in enumerate(instance.pathways):
        if pathway.capacity is None:
            continue
        problem += (
            pulp.lpSum(
                representatives[(cohort_id, pathway.pathway_id)][3] * variable
                for (cohort_id, pathway_id), variable in variables.items()
                if pathway_id == pathway.pathway_id
            )
            <= pathway.capacity,
            f"pathway_capacity_{index}",
        )
    for resource_index, resource in enumerate(instance.resources):
        problem += (
            pulp.lpSum(
                representatives[(cohort_id, pathway_id)][4].get(resource.resource_id, 0.0)
                * variable
                for (cohort_id, pathway_id), variable in variables.items()
                if pathway_id is not None
            )
            <= resource.capacity,
            f"resource_capacity_{resource_index}",
        )
    if instance.co2_floor_kg is not None:
        problem += (
            pulp.lpSum(
                representatives[(cohort_id, pathway_id)][2] * variable
                for (cohort_id, pathway_id), variable in variables.items()
                if pathway_id is not None
            )
            >= instance.co2_floor_kg,
            "co2_floor",
        )
    problem.solve(make_cbc_solver())
    status = _exact_solve_status(problem)
    if status != "Optimal":
        return CohortSolveResult(
            status,
            scheme,
            len(cohorts),
            sufficiency.sufficient,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            {},
        )
    counts = {
        key: int(round(variable.value() or 0.0)) for key, variable in variables.items()
    }
    representative_objective = float(pulp.value(problem.objective))

    lift = pulp.LpProblem("level0_cohort_lift", pulp.LpMaximize)
    z: dict[tuple[str, str | None], pulp.LpVariable] = {}
    asset_to_cohort = {
        asset.asset_id: cohort_id for cohort_id, assets in cohorts.items() for asset in assets
    }
    for asset_index, asset in enumerate(instance.assets):
        cohort_id = asset_to_cohort[asset.asset_id]
        for pathway_index, pathway in enumerate(instance.pathways):
            if counts.get((cohort_id, pathway.pathway_id), 0) > 0:
                coefficient = instance.coefficients[(asset.asset_id, pathway.pathway_id)]
                if coefficient.admissible:
                    z[(asset.asset_id, pathway.pathway_id)] = lift.add_variable(
                        f"z_{asset_index}_{pathway_index}", cat=pulp.LpBinary
                    )
        z[(asset.asset_id, None)] = lift.add_variable(f"zd_{asset_index}", cat=pulp.LpBinary)
    lift += pulp.lpSum(
        instance.coefficients[(asset_id, pathway_id)].economic_value * variable
        if pathway_id is not None
        else -instance.deferral_costs[asset_id] * variable
        for (asset_id, pathway_id), variable in z.items()
    )
    for index, asset in enumerate(instance.assets):
        lift += (
            pulp.lpSum(
                variable
                for (asset_id, _), variable in z.items()
                if asset_id == asset.asset_id
            )
            == 1,
            f"asset_{index}",
        )
    for cohort_index, (cohort_id, assets) in enumerate(cohorts.items()):
        for pathway_index, pathway_id in enumerate(
            [pathway.pathway_id for pathway in instance.pathways] + [None]
        ):
            lift += (
                pulp.lpSum(
                    variable
                    for (asset_id, candidate_pathway), variable in z.items()
                    if asset_id in {asset.asset_id for asset in assets}
                    and candidate_pathway == pathway_id
                )
                == counts.get((cohort_id, pathway_id), 0),
                f"fixed_{cohort_index}_{pathway_index}",
            )
    if instance.co2_floor_kg is not None:
        lift += (
            pulp.lpSum(
                instance.coefficients[(asset_id, pathway_id)].avoided_co2_kg * variable
                for (asset_id, pathway_id), variable in z.items()
                if pathway_id is not None
            )
            >= instance.co2_floor_kg,
            "co2_floor",
        )
    lift.solve(make_cbc_solver())
    lift_status = _exact_solve_status(lift)
    if lift_status != "Optimal":
        return CohortSolveResult(
            lift_status,
            scheme,
            len(cohorts),
            sufficiency.sufficient,
            representative_objective,
            None,
            None,
            None,
            None,
            None,
            None,
            counts,
        )
    lifted_action = AllocationAction(
        {
            asset.asset_id: next(
                pathway_id
                for (asset_id, pathway_id), variable in z.items()
                if asset_id == asset.asset_id and (variable.value() or 0.0) > 0.5
            )
            for asset in instance.assets
        }
    )
    lifted_evaluation = evaluate_action(instance, lifted_action)
    if not lifted_evaluation.feasible:
        raise RuntimeError(
            "lifted cohort action is not implementable: "
            + "; ".join(lifted_evaluation.violations)
        )
    asset_result = solve_milp(instance)
    asset_objective = (
        asset_result.evaluation.economic_objective
        if asset_result.optimal and asset_result.evaluation is not None
        else None
    )
    representative_gap = (
        asset_objective - representative_objective if asset_objective is not None else None
    )
    lifted_gap = (
        asset_objective - lifted_evaluation.economic_objective
        if asset_objective is not None
        else None
    )
    lifted_gap_percent = (
        100.0 * lifted_gap / abs(asset_objective)
        if asset_objective is not None and abs(asset_objective) > 1e-9 and lifted_gap is not None
        else None
    )
    return CohortSolveResult(
        "Optimal",
        scheme,
        len(cohorts),
        sufficiency.sufficient,
        representative_objective,
        lifted_action,
        lifted_evaluation,
        asset_objective,
        representative_gap,
        lifted_gap,
        lifted_gap_percent,
        counts,
    )
