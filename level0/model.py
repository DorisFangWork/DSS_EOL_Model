"""PuLP-isolated Level 0 MILP, LP relaxation, and emissions endpoint."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType
from typing import Literal, Mapping

import pulp

from dss.allocation import AllocationAction, EvaluationReport

from .evaluation import evaluate_action
from .instance import StaticAllocationInstance


@dataclass(frozen=True, slots=True)
class SolverOptions:
    msg: bool = False
    threads: int = 1
    time_limit_seconds: float | None = None
    relative_gap: float | None = None
    # CBC interprets zero as "seed from the current time", so the default must
    # be positive to make solver behaviour genuinely reproducible.
    random_seed: int = 20260802

    def __post_init__(self) -> None:
        if isinstance(self.threads, bool) or not isinstance(self.threads, int) or self.threads <= 0:
            raise ValueError("threads must be a positive integer")
        if self.time_limit_seconds is not None:
            raise ValueError("time_limit_seconds must be None for exact Level 0 solves")
        if self.relative_gap not in (None, 0, 0.0):
            raise ValueError("relative_gap must be None or 0 for exact Level 0 solves")
        if (
            isinstance(self.random_seed, bool)
            or not isinstance(self.random_seed, int)
            or self.random_seed <= 0
        ):
            raise ValueError("random_seed must be a positive integer; CBC treats zero as time-based")


@dataclass(frozen=True, slots=True)
class SolverDiagnostics:
    status: str
    raw_status: int
    solution_status: str
    raw_solution_status: int
    exact_certificate: bool
    solver_name: str
    optimized_metric: str
    optimized_objective: float | None
    options: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "options", MappingProxyType(dict(self.options)))


@dataclass(frozen=True, slots=True)
class ShadowPrice:
    constraint_key: str
    constraint_kind: str
    entity_id: str
    rhs: float
    use: float
    slack: float
    raw_dual: float
    marginal_value: float
    binding: bool
    tolerance: float
    source: str = "lp_relaxation"


@dataclass(frozen=True, slots=True)
class SolveResult:
    status: str
    action: AllocationAction | None
    evaluation: EvaluationReport | None
    diagnostics: SolverDiagnostics

    @property
    def optimal(self) -> bool:
        return self.diagnostics.exact_certificate


@dataclass(frozen=True, slots=True)
class RelaxationResult:
    status: str
    allocation_fractions: Mapping[tuple[str, str], float]
    deferral_fractions: Mapping[str, float]
    economic_objective: float | None
    avoided_co2_kg: float | None
    shadow_prices: Mapping[str, ShadowPrice]
    diagnostics: SolverDiagnostics

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "allocation_fractions", MappingProxyType(dict(self.allocation_fractions))
        )
        object.__setattr__(
            self, "deferral_fractions", MappingProxyType(dict(self.deferral_fractions))
        )
        object.__setattr__(self, "shadow_prices", MappingProxyType(dict(self.shadow_prices)))

    @property
    def optimal(self) -> bool:
        return self.diagnostics.exact_certificate


@dataclass(slots=True)
class _BuiltProblem:
    problem: pulp.LpProblem
    allocation_variables: dict[tuple[str, str], pulp.LpVariable]
    deferral_variables: dict[str, pulp.LpVariable]
    constraint_keys: dict[str, tuple[str, str, float]]


def make_cbc_solver(options: SolverOptions | None = None) -> pulp.COIN_CMD:
    """Use PuLP's bundled CBC executable through the non-deprecated COIN API."""

    options = options or SolverOptions()
    return pulp.COIN_CMD(
        path=str(pulp.PULP_CBC_CMD.pulp_cbc_path),
        msg=options.msg,
        threads=options.threads,
        timeLimit=options.time_limit_seconds,
        gapRel=options.relative_gap,
        options=[
            f"randomSeed {options.random_seed}",
            f"randomCbcSeed {options.random_seed}",
        ],
    )


def _build_problem(
    instance: StaticAllocationInstance,
    *,
    relaxation: bool,
    objective_kind: Literal["economic", "emissions"],
) -> _BuiltProblem:
    problem = pulp.LpProblem(f"level0_{objective_kind}", pulp.LpMaximize)
    category = pulp.LpContinuous if relaxation else pulp.LpBinary
    allocation_variables: dict[tuple[str, str], pulp.LpVariable] = {}
    deferral_variables: dict[str, pulp.LpVariable] = {}

    for asset_index, asset in enumerate(instance.assets):
        for pathway_index, pathway in enumerate(instance.pathways):
            coefficient = instance.coefficients[(asset.asset_id, pathway.pathway_id)]
            if coefficient.admissible:
                allocation_variables[(asset.asset_id, pathway.pathway_id)] = problem.add_variable(
                    f"x_{asset_index}_{pathway_index}", lowBound=0, upBound=1, cat=category
                )
        deferral_variables[asset.asset_id] = problem.add_variable(
            f"d_{asset_index}", lowBound=0, upBound=1, cat=category
        )

    economic_expression = pulp.lpSum(
        instance.coefficients[key].economic_value * variable
        for key, variable in allocation_variables.items()
    ) - pulp.lpSum(
        instance.deferral_costs[asset_id] * variable
        for asset_id, variable in deferral_variables.items()
    )
    emissions_expression = pulp.lpSum(
        instance.coefficients[key].avoided_co2_kg * variable
        for key, variable in allocation_variables.items()
    )
    problem += (
        economic_expression if objective_kind == "economic" else emissions_expression,
        f"maximize_{objective_kind}",
    )

    constraint_keys: dict[str, tuple[str, str, float]] = {}
    for asset_index, asset in enumerate(instance.assets):
        name = f"assignment_{asset_index}"
        problem += (
            pulp.lpSum(
                variable
                for (asset_id, _), variable in allocation_variables.items()
                if asset_id == asset.asset_id
            )
            + deferral_variables[asset.asset_id]
            == 1,
            name,
        )

    for pathway_index, pathway in enumerate(instance.pathways):
        if pathway.capacity is None:
            continue
        name = f"pathway_capacity_{pathway_index}"
        problem += (
            pulp.lpSum(
                instance.coefficients[key].pathway_capacity_use * variable
                for key, variable in allocation_variables.items()
                if key[1] == pathway.pathway_id
            )
            <= pathway.capacity,
            name,
        )
        constraint_keys[name] = ("pathway_capacity", pathway.pathway_id, pathway.capacity)

    for resource_index, resource in enumerate(instance.resources):
        name = f"resource_capacity_{resource_index}"
        problem += (
            pulp.lpSum(
                instance.coefficients[key].resource_use.get(resource.resource_id, 0.0)
                * variable
                for key, variable in allocation_variables.items()
            )
            <= resource.capacity,
            name,
        )
        constraint_keys[name] = ("resource_capacity", resource.resource_id, resource.capacity)

    if instance.co2_floor_kg is not None:
        name = "co2_floor"
        problem += emissions_expression >= instance.co2_floor_kg, name
        constraint_keys[name] = ("co2_floor", "avoided_co2_kg", instance.co2_floor_kg)

    return _BuiltProblem(
        problem=problem,
        allocation_variables=allocation_variables,
        deferral_variables=deferral_variables,
        constraint_keys=constraint_keys,
    )


def _diagnostics(
    problem: pulp.LpProblem,
    options: SolverOptions,
    objective_kind: str,
) -> SolverDiagnostics:
    raw_status = int(problem.status)
    raw_solution_status = int(getattr(problem, "sol_status", pulp.LpSolutionNoSolutionFound))
    model_status = pulp.LpStatus.get(raw_status, f"Unknown({raw_status})")
    solution_status = pulp.LpSolution.get(
        raw_solution_status, f"Unknown({raw_solution_status})"
    )
    exact_certificate = (
        raw_status == pulp.LpStatusOptimal
        and raw_solution_status == pulp.LpSolutionOptimal
    )
    if exact_certificate:
        status = "Optimal"
    elif raw_solution_status == pulp.LpSolutionIntegerFeasible:
        status = "FeasibleNotProvenOptimal"
    elif model_status == "Optimal":
        status = "NoExactCertificate"
    else:
        status = model_status
    objective = (
        pulp.value(problem.objective)
        if raw_solution_status in (pulp.LpSolutionOptimal, pulp.LpSolutionIntegerFeasible)
        else None
    )
    return SolverDiagnostics(
        status=status,
        raw_status=raw_status,
        solution_status=solution_status,
        raw_solution_status=raw_solution_status,
        exact_certificate=exact_certificate,
        solver_name="COIN_CMD (bundled CBC)",
        optimized_metric=objective_kind,
        optimized_objective=float(objective) if objective is not None else None,
        options={
            "msg": options.msg,
            "threads": options.threads,
            "time_limit_seconds": options.time_limit_seconds,
            "relative_gap": options.relative_gap,
            "random_seed": options.random_seed,
        },
    )


def _extract_integer_action(built: _BuiltProblem) -> AllocationAction:
    assignments: dict[str, str | None] = {}
    for asset_id, deferral_variable in built.deferral_variables.items():
        selected = sorted(
            pathway_id
            for (candidate_asset_id, pathway_id), variable in built.allocation_variables.items()
            if candidate_asset_id == asset_id and (variable.value() or 0.0) > 0.5
        )
        if len(selected) > 1:
            raise RuntimeError(f"solver returned multiple pathways for asset {asset_id}")
        if selected:
            assignments[asset_id] = selected[0]
        elif (deferral_variable.value() or 0.0) > 0.5:
            assignments[asset_id] = None
        else:
            raise RuntimeError(f"solver returned no integral action for asset {asset_id}")
    return AllocationAction(assignments)


def _solve_integer(
    instance: StaticAllocationInstance,
    *,
    objective_kind: Literal["economic", "emissions"],
    options: SolverOptions,
) -> SolveResult:
    built = _build_problem(instance, relaxation=False, objective_kind=objective_kind)
    built.problem.solve(make_cbc_solver(options))
    diagnostics = _diagnostics(built.problem, options, objective_kind)
    if diagnostics.status != "Optimal":
        return SolveResult(diagnostics.status, None, None, diagnostics)
    action = _extract_integer_action(built)
    evaluation = evaluate_action(instance, action)
    if not evaluation.feasible:
        raise RuntimeError(
            "solver returned an action that failed independent evaluation: "
            + "; ".join(evaluation.violations)
        )
    if objective_kind == "economic" and diagnostics.optimized_objective is not None:
        if abs(diagnostics.optimized_objective - evaluation.economic_objective) > 1e-5:
            raise RuntimeError("solver objective does not reconcile with independent evaluation")
    return SolveResult(diagnostics.status, action, evaluation, diagnostics)


def solve_milp(
    instance: StaticAllocationInstance,
    options: SolverOptions | None = None,
) -> SolveResult:
    """Solve the exact operational one-period allocation MILP."""

    return _solve_integer(
        instance,
        objective_kind="economic",
        options=options or SolverOptions(),
    )


def solve_emissions_endpoint(
    instance: StaticAllocationInstance,
    options: SolverOptions | None = None,
) -> SolveResult:
    """Maximise feasible avoided emissions with the same operational constraints."""

    return _solve_integer(
        instance,
        objective_kind="emissions",
        options=options or SolverOptions(),
    )


def _fractional_use(
    instance: StaticAllocationInstance,
    fractions: Mapping[tuple[str, str], float],
    kind: str,
    entity_id: str,
) -> float:
    if kind == "pathway_capacity":
        return sum(
            instance.coefficients[key].pathway_capacity_use * value
            for key, value in fractions.items()
            if key[1] == entity_id
        )
    if kind == "resource_capacity":
        return sum(
            instance.coefficients[key].resource_use.get(entity_id, 0.0) * value
            for key, value in fractions.items()
        )
    if kind == "co2_floor":
        return sum(
            instance.coefficients[key].avoided_co2_kg * value
            for key, value in fractions.items()
        )
    raise KeyError(kind)


def solve_lp_relaxation(
    instance: StaticAllocationInstance,
    options: SolverOptions | None = None,
    *,
    tolerance: float = 1e-7,
) -> RelaxationResult:
    """Solve a fresh continuous relaxation and extract LP-only shadow prices."""

    solver_options = options or SolverOptions()
    built = _build_problem(instance, relaxation=True, objective_kind="economic")
    built.problem.solve(make_cbc_solver(solver_options))
    diagnostics = _diagnostics(built.problem, solver_options, "economic_lp_relaxation")
    if diagnostics.status != "Optimal":
        return RelaxationResult(
            status=diagnostics.status,
            allocation_fractions={},
            deferral_fractions={},
            economic_objective=None,
            avoided_co2_kg=None,
            shadow_prices={},
            diagnostics=diagnostics,
        )

    fractions = {
        key: float(variable.value() or 0.0)
        for key, variable in built.allocation_variables.items()
    }
    deferrals = {
        asset_id: float(variable.value() or 0.0)
        for asset_id, variable in built.deferral_variables.items()
    }
    economic = sum(
        instance.coefficients[key].economic_value * value for key, value in fractions.items()
    ) - sum(instance.deferral_costs[key] * value for key, value in deferrals.items())
    emissions = sum(
        instance.coefficients[key].avoided_co2_kg * value for key, value in fractions.items()
    )
    shadow_prices: dict[str, ShadowPrice] = {}
    for constraint_name, (kind, entity_id, rhs) in built.constraint_keys.items():
        constraint = built.problem.get_constraint_by_name(constraint_name)
        if constraint is None:
            raise RuntimeError(f"missing LP constraint {constraint_name}")
        raw_dual = float(constraint.pi or 0.0)
        use = _fractional_use(instance, fractions, kind, entity_id)
        slack = rhs - use if kind != "co2_floor" else use - rhs
        marginal_value = -raw_dual if kind == "co2_floor" else raw_dual
        if not isfinite(marginal_value):
            marginal_value = 0.0
        shadow_prices[constraint_name] = ShadowPrice(
            constraint_key=constraint_name,
            constraint_kind=kind,
            entity_id=entity_id,
            rhs=float(rhs),
            use=float(use),
            slack=float(slack),
            raw_dual=raw_dual,
            marginal_value=marginal_value,
            binding=abs(slack) <= tolerance,
            tolerance=tolerance,
        )

    return RelaxationResult(
        status=diagnostics.status,
        allocation_fractions=fractions,
        deferral_fractions=deferrals,
        economic_objective=economic,
        avoided_co2_kg=emissions,
        shadow_prices=shadow_prices,
        diagnostics=diagnostics,
    )


def available_solvers() -> tuple[str, ...]:
    solver = make_cbc_solver()
    return ("COIN_CMD (bundled CBC)",) if solver.available() else ()
