"""Mathematical, feasibility, and limiting-case verification for Level 0."""

from __future__ import annotations

from dataclasses import dataclass

from .evaluation import evaluate_action
from .instance import StaticAllocationInstance
from .model import SolveResult, solve_emissions_endpoint, solve_lp_relaxation, solve_milp
from .policies import fifo, greedy_value, independent_best, soh_threshold


@dataclass(frozen=True, slots=True)
class VerificationCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class VerificationReport:
    checks: tuple[VerificationCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> tuple[VerificationCheck, ...]:
        return tuple(check for check in self.checks if not check.passed)


def verify_solution(
    instance: StaticAllocationInstance,
    result: SolveResult,
    *,
    tolerance: float = 1e-6,
) -> VerificationReport:
    checks: list[VerificationCheck] = []
    checks.append(
        VerificationCheck(
            "optimal_status",
            result.optimal,
            f"solver status is {result.status}",
        )
    )
    if result.action is None or result.evaluation is None:
        checks.append(VerificationCheck("action_present", False, "no action/evaluation returned"))
        return VerificationReport(tuple(checks))

    checks.append(
        VerificationCheck(
            "exactly_one_action",
            set(result.action.assignments) == set(instance.asset_by_id),
            f"declared {len(result.action.assignments)} actions for {len(instance.assets)} assets",
        )
    )
    recomputed = evaluate_action(instance, result.action)
    checks.append(
        VerificationCheck(
            "independent_feasibility",
            recomputed.feasible,
            "; ".join(recomputed.violations) if recomputed.violations else "no violations",
        )
    )
    objective_match = (
        abs(recomputed.economic_objective - result.evaluation.economic_objective) <= tolerance
    )
    checks.append(
        VerificationCheck(
            "objective_reconciliation",
            objective_match,
            f"reported={result.evaluation.economic_objective:.9g}, "
            f"recomputed={recomputed.economic_objective:.9g}",
        )
    )
    emissions_match = abs(recomputed.avoided_co2_kg - result.evaluation.avoided_co2_kg) <= tolerance
    checks.append(
        VerificationCheck(
            "emissions_reconciliation",
            emissions_match,
            f"reported={result.evaluation.avoided_co2_kg:.9g}, "
            f"recomputed={recomputed.avoided_co2_kg:.9g}",
        )
    )
    return VerificationReport(tuple(checks))


def run_reduction_checks(
    instance: StaticAllocationInstance,
    *,
    tolerance: float = 1e-5,
) -> VerificationReport:
    checks: list[VerificationCheck] = []
    milp = solve_milp(instance)
    checks.extend(verify_solution(instance, milp, tolerance=tolerance).checks)
    if not milp.optimal or milp.evaluation is None or milp.action is None:
        return VerificationReport(tuple(checks))

    relaxation = solve_lp_relaxation(instance)
    lp_bound_ok = (
        relaxation.optimal
        and relaxation.economic_objective is not None
        and relaxation.economic_objective + tolerance >= milp.evaluation.economic_objective
    )
    checks.append(
        VerificationCheck(
            "lp_upper_bound",
            lp_bound_ok,
            f"LP={relaxation.economic_objective}, MILP={milp.evaluation.economic_objective}",
        )
    )

    for name, action in (
        ("greedy_value", greedy_value(instance)),
        ("soh_threshold", soh_threshold(instance)),
        ("fifo", fifo(instance)),
    ):
        evaluation = evaluate_action(instance, action)
        dominated = evaluation.feasible and (
            milp.evaluation.economic_objective + tolerance >= evaluation.economic_objective
        )
        checks.append(
            VerificationCheck(
                f"milp_dominates_{name}",
                dominated,
                f"feasible={evaluation.feasible}, policy={evaluation.economic_objective:.9g}, "
                f"MILP={milp.evaluation.economic_objective:.9g}",
            )
        )

    maximum_resource_use = {
        resource.resource_id: sum(
            max(
                instance.coefficients[(asset.asset_id, pathway.pathway_id)].resource_use.get(
                    resource.resource_id, 0.0
                )
                for pathway in instance.pathways
            )
            for asset in instance.assets
        )
        for resource in instance.resources
    }
    uncoupled = instance.with_capacities(
        pathway_capacities={p.pathway_id: None for p in instance.pathways},
        resource_capacities=maximum_resource_use,
        scenario_label=f"{instance.scenario_label}_uncoupled",
    ).with_co2_floor(None)
    uncoupled_milp = solve_milp(uncoupled)
    independent = independent_best(uncoupled)
    independent_evaluation = evaluate_action(uncoupled, independent)
    collapse_ok = (
        uncoupled_milp.optimal
        and uncoupled_milp.evaluation is not None
        and independent_evaluation.feasible
        and abs(
            uncoupled_milp.evaluation.economic_objective
            - independent_evaluation.economic_objective
        )
        <= tolerance
    )
    checks.append(
        VerificationCheck(
            "unlimited_capacity_collapse",
            collapse_ok,
            f"MILP={uncoupled_milp.evaluation.economic_objective if uncoupled_milp.evaluation else None}, "
            f"independent={independent_evaluation.economic_objective}",
        )
    )

    zero_capacity = instance.with_capacities(
        pathway_capacities={p.pathway_id: 0.0 for p in instance.pathways},
        resource_capacities={r.resource_id: 0.0 for r in instance.resources},
        scenario_label=f"{instance.scenario_label}_zero_capacity",
    ).with_co2_floor(None)
    zero_result = solve_milp(zero_capacity)
    all_deferred = (
        zero_result.optimal
        and zero_result.action is not None
        and all(pathway is None for pathway in zero_result.action.assignments.values())
    )
    checks.append(
        VerificationCheck(
            "zero_capacity_deferral_feasible",
            all_deferred,
            f"status={zero_result.status}",
        )
    )

    repeated = solve_milp(instance)
    deterministic = (
        repeated.optimal
        and repeated.evaluation is not None
        and abs(repeated.evaluation.economic_objective - milp.evaluation.economic_objective)
        <= tolerance
        and repeated.action == milp.action
    )
    checks.append(
        VerificationCheck(
            "deterministic_repeat",
            deterministic,
            "repeated solve reproduces objective and action",
        )
    )

    # Call-order mutation guard: none of these solves may change the input instance.
    solve_lp_relaxation(instance)
    solve_emissions_endpoint(instance.with_co2_floor(None))
    after_other_solves = solve_milp(instance)
    call_order_ok = (
        after_other_solves.optimal
        and after_other_solves.evaluation is not None
        and abs(
            after_other_solves.evaluation.economic_objective
            - milp.evaluation.economic_objective
        )
        <= tolerance
        and after_other_solves.action == milp.action
    )
    checks.append(
        VerificationCheck(
            "solve_call_order_independence",
            call_order_ok,
            "MILP -> LP -> emissions -> MILP is stable",
        )
    )
    return VerificationReport(tuple(checks))


def assert_verified(report: VerificationReport) -> None:
    if not report.passed:
        details = "\n".join(
            f"- {check.name}: {check.detail}" for check in report.failures
        )
        raise AssertionError(f"Level 0 verification failed:\n{details}")

