from __future__ import annotations

from dataclasses import replace

import pytest

from dss.allocation import AllocationAction
from dss.domain import Asset, PairCoefficients, PathwaySpec, ResourceSpec
from dss.policy import DecisionContext, FleetState, Policy
from level0.adapters import MyopicMILPPolicy, fixed_instance_builder
from level0.cohorts import CohortScheme, check_sufficiency, solve_aggregated
from level0.evaluation import evaluate_action
from level0.instance import (
    StaticAllocationInstance,
    ValuationParams,
    build_instance,
    default_instance,
    generate_fleet,
)
from level0.model import (
    SolverOptions,
    make_cbc_solver,
    solve_emissions_endpoint,
    solve_lp_relaxation,
    solve_milp,
)
from level0.policies import greedy_value, independent_best, soh_threshold
from level0.verify import run_reduction_checks


def test_domain_and_instance_validation(scarcity_instance):
    with pytest.raises(ValueError, match="soh"):
        Asset("bad", 1.1, "NMC", 0, 50, 300)
    with pytest.raises(ValueError, match="positive"):
        Asset("bad", 0.8, "NMC", 0, 0, 300)
    with pytest.raises(ValueError, match="integer"):
        Asset("bad", 0.8, "NMC", 0.5, 50, 300)
    with pytest.raises(ValueError, match="integer"):
        Asset("bad", 0.8, "NMC", 0, 50, 300, periods_held=1.5)
    with pytest.raises(ValueError, match="integer"):
        FleetState((), period=0.5)
    with pytest.raises(ValueError, match="non-negative"):
        ResourceSpec("r", "Resource", -1)
    duplicate = (scarcity_instance.assets[0], scarcity_instance.assets[0])
    with pytest.raises(ValueError, match="unique"):
        StaticAllocationInstance(
            assets=duplicate,
            pathways=scarcity_instance.pathways,
            resources=(),
            coefficients=scarcity_instance.coefficients,
            deferral_costs={"H": 2},
        )
    asset = scarcity_instance.assets[0]
    nonterminal = PathwaySpec("future", "Future", terminal=False)
    with pytest.raises(ValueError, match="terminal"):
        StaticAllocationInstance(
            assets=(asset,),
            pathways=(nonterminal,),
            resources=(),
            coefficients={
                (asset.asset_id, "future"): PairCoefficients(
                    asset.asset_id, "future", True, 1, 1
                )
            },
            deferral_costs={asset.asset_id: 0},
        )


def test_state_and_instance_normalize_mutable_sequences():
    asset = Asset("A", 0.8, "NMC", 0, 50, 300)
    extra = Asset("B", 0.8, "NMC", 0, 50, 300)
    asset_source = [asset]
    state = FleetState(asset_source)
    asset_source.append(extra)
    assert state.assets == (asset,)

    pathway = PathwaySpec("process", "Process")
    instance_assets = [asset]
    instance_pathways = [pathway]
    instance_resources = []
    instance = StaticAllocationInstance(
        instance_assets,
        instance_pathways,
        instance_resources,
        {("A", "process"): PairCoefficients("A", "process", True, 1, 0)},
        {"A": 0},
    )
    instance_assets.append(extra)
    instance_pathways.clear()
    instance_resources.append(ResourceSpec("r", "Resource", 1))
    assert instance.assets == (asset,)
    assert instance.pathways == (pathway,)
    assert instance.resources == ()
    assert solve_milp(instance).optimal


def test_default_valuation_rejects_missing_admissible_chemistry_parameters():
    asset = Asset("X", 0.8, "LCO", 0, 50, 300)
    pathway = PathwaySpec(
        "repurpose", "Repurpose", allowed_chemistries=("LCO",)
    )
    with pytest.raises(KeyError, match="economic parameter"):
        build_instance(assets=(asset,), pathways=(pathway,), resources=())
    params = ValuationParams(repurpose_chemistry_multiplier={"LCO": 1.0})
    with pytest.raises(KeyError, match="emissions parameter"):
        build_instance(
            assets=(asset,),
            pathways=(pathway,),
            resources=(),
            valuation=params,
        )


def test_default_valuation_is_auditable_and_admissibility_is_sparse():
    instance = default_instance(size=8, seed=7)
    result = solve_lp_relaxation(instance)
    assert result.optimal
    for asset in instance.assets:
        coefficient = instance.coefficients[(asset.asset_id, "repurpose")]
        if not coefficient.admissible:
            assert (asset.asset_id, "repurpose") not in result.allocation_fractions
        recycle = instance.coefficients[(asset.asset_id, "recycle")]
        assert recycle.avoided_co2_kg >= 0
        assert recycle.economic_value == pytest.approx(
            asset.mass_kg
            * (
                instance.metadata["valuation"].recycling_value_per_kg[asset.chemistry]
                - instance.metadata["valuation"].recycling_cost_per_kg
            )
            - asset.safety_class * instance.metadata["valuation"].safety_handling_cost
        )


def test_exact_milp_scarcity_solution(scarcity_instance):
    result = solve_milp(scarcity_instance)
    assert result.optimal
    assert result.action.assignments == {"H": "recycle", "M": "repurpose", "L": "recycle"}
    assert result.evaluation.economic_objective == pytest.approx(21)
    assert result.evaluation.avoided_co2_kg == pytest.approx(17)


def test_exact_solver_options_use_fixed_cbc_seeds_and_both_certificates(
    scarcity_instance,
):
    options = SolverOptions()
    solver = make_cbc_solver(options)
    assert options.random_seed > 0
    assert f"randomSeed {options.random_seed}" in solver.options
    assert f"randomCbcSeed {options.random_seed}" in solver.options
    result = solve_milp(scarcity_instance, options)
    assert result.diagnostics.exact_certificate
    assert result.diagnostics.solution_status == "Optimal Solution Found"
    assert result.diagnostics.solver_name == "COIN_CMD (bundled CBC)"
    with pytest.raises(ValueError, match="time-based"):
        SolverOptions(random_seed=0)
    with pytest.raises(ValueError, match="exact"):
        SolverOptions(relative_gap=0.01)
    with pytest.raises(ValueError, match="exact"):
        SolverOptions(time_limit_seconds=1)


def test_zero_terminal_capacity_defers_and_remains_feasible(scarcity_instance):
    zero = scarcity_instance.with_capacities(
        pathway_capacities={"repurpose": 0, "recycle": 0}
    )
    result = solve_milp(zero)
    assert result.optimal
    assert all(value is None for value in result.action.assignments.values())
    assert result.evaluation.economic_objective == pytest.approx(-6)


def test_shared_resource_couples_pathways():
    assets = (
        Asset("A", 0.8, "NMC", 0, 50, 300),
        Asset("B", 0.8, "NMC", 0, 50, 300),
    )
    pathways = (PathwaySpec("heavy", "Heavy"), PathwaySpec("light", "Light"))
    coefficients = {
        ("A", "heavy"): PairCoefficients("A", "heavy", True, 10, 0, resource_use={"r": 2}),
        ("A", "light"): PairCoefficients("A", "light", True, 6, 0, resource_use={"r": 1}),
        ("B", "heavy"): PairCoefficients("B", "heavy", True, 9, 0, resource_use={"r": 2}),
        ("B", "light"): PairCoefficients("B", "light", True, 8, 0, resource_use={"r": 1}),
    }
    instance = StaticAllocationInstance(
        assets,
        pathways,
        (ResourceSpec("r", "Shared", 2),),
        coefficients,
        {"A": 0, "B": 0},
    )
    result = solve_milp(instance)
    assert result.evaluation.economic_objective == pytest.approx(14)
    assert result.action.assignments == {"A": "light", "B": "light"}


def test_result_reconciles_with_independent_evaluator(scarcity_instance):
    result = solve_milp(scarcity_instance)
    evaluated = evaluate_action(scarcity_instance, result.action)
    assert evaluated.feasible
    assert evaluated == result.evaluation
    assert evaluated.pathway_use == {"repurpose": 1, "recycle": 2}


def test_unlimited_capacity_reduces_to_independent_choice(scarcity_instance):
    uncoupled = scarcity_instance.with_capacities(pathway_capacities={"repurpose": 2})
    milp = solve_milp(uncoupled)
    independent = independent_best(uncoupled)
    independent_evaluation = evaluate_action(uncoupled, independent)
    assert independent_evaluation.feasible
    assert milp.evaluation.economic_objective == pytest.approx(22)
    assert milp.evaluation.economic_objective == pytest.approx(
        independent_evaluation.economic_objective
    )


def test_lp_relaxation_has_real_integrality_gap(lp_dual_instance):
    milp = solve_milp(lp_dual_instance)
    relaxation = solve_lp_relaxation(lp_dual_instance)
    assert milp.evaluation.economic_objective == pytest.approx(2)
    assert relaxation.economic_objective == pytest.approx(3)
    assert relaxation.economic_objective >= milp.evaluation.economic_objective
    assert any(0 < value < 1 for value in relaxation.allocation_fractions.values())


def test_lp_dual_matches_finite_capacity_difference(lp_dual_instance):
    base = solve_lp_relaxation(lp_dual_instance)
    perturbed = lp_dual_instance.with_capacities(resource_capacities={"machine": 3.1})
    changed = solve_lp_relaxation(perturbed)
    shadow = next(iter(base.shadow_prices.values()))
    finite_difference = (changed.economic_objective - base.economic_objective) / 0.1
    assert shadow.marginal_value == pytest.approx(1, abs=1e-6)
    assert finite_difference == pytest.approx(shadow.marginal_value, abs=1e-6)


def test_evaluator_flags_incomplete_unknown_inadmissible_and_capacity(scarcity_instance):
    incomplete = evaluate_action(scarcity_instance, AllocationAction({"H": "recycle"}))
    assert not incomplete.feasible
    unknown = evaluate_action(
        scarcity_instance,
        AllocationAction({"H": "unknown", "M": "recycle", "L": "recycle"}),
    )
    assert not unknown.feasible
    inadmissible = evaluate_action(
        scarcity_instance,
        AllocationAction({"H": "recycle", "M": "recycle", "L": "repurpose"}),
    )
    assert not inadmissible.feasible
    independent = evaluate_action(scarcity_instance, independent_best(scarcity_instance))
    assert not independent.feasible
    assert any("capacity" in violation for violation in independent.violations)


def test_milp_dominates_only_feasible_baselines(scarcity_instance):
    milp = solve_milp(scarcity_instance)
    greedy = evaluate_action(scarcity_instance, greedy_value(scarcity_instance))
    threshold = evaluate_action(scarcity_instance, soh_threshold(scarcity_instance, threshold=0.7))
    assert greedy.feasible and threshold.feasible
    assert milp.evaluation.economic_objective >= greedy.economic_objective
    assert milp.evaluation.economic_objective >= threshold.economic_objective
    assert evaluate_action(scarcity_instance, independent_best(scarcity_instance)).economic_objective == 22


def test_emissions_endpoint_frontier_and_infeasible_floor(emissions_instance):
    economic = solve_milp(emissions_instance)
    endpoint = solve_emissions_endpoint(emissions_instance)
    constrained = solve_milp(emissions_instance.with_co2_floor(5))
    impossible = solve_milp(emissions_instance.with_co2_floor(11))
    assert economic.evaluation.economic_objective == pytest.approx(10)
    assert economic.evaluation.avoided_co2_kg == pytest.approx(0)
    assert endpoint.evaluation.avoided_co2_kg == pytest.approx(10)
    assert constrained.evaluation.economic_objective == pytest.approx(8)
    assert impossible.status == "Infeasible"


def test_emissions_lp_shadow_is_normalized_cost(emissions_instance):
    relaxation = solve_lp_relaxation(emissions_instance.with_co2_floor(5))
    shadow = next(
        value for value in relaxation.shadow_prices.values() if value.constraint_kind == "co2_floor"
    )
    assert relaxation.economic_objective == pytest.approx(9)
    assert shadow.marginal_value == pytest.approx(0.2)


def test_singleton_cohorts_exact_and_integer_counts(cohort_instance):
    result = solve_aggregated(
        cohort_instance,
        CohortScheme(soh_band_width=None, include_asset_id=True),
    )
    assert result.status == "Optimal"
    assert result.lifted_evaluation.feasible
    assert result.lifted_evaluation.economic_objective == pytest.approx(11)
    assert sum(
        count
        for (cohort, pathway), count in result.cohort_pathway_counts.items()
        if pathway == "repurpose"
    ) == 2
    assert result.lifted_gap == pytest.approx(0)


def test_cohort_sufficiency_detects_admissibility_cliff():
    assets = (
        Asset("below", 0.69, "NMC", 0, 50, 300),
        Asset("above", 0.71, "NMC", 0, 50, 300),
    )
    pathways = (PathwaySpec("repurpose", "Repurpose", min_soh=0.70),)
    coefficients = {
        ("below", "repurpose"): PairCoefficients("below", "repurpose", False, 1, 1),
        ("above", "repurpose"): PairCoefficients("above", "repurpose", True, 2, 2),
    }
    instance = StaticAllocationInstance(
        assets, pathways, (), coefficients, {"below": 1, "above": 1}
    )
    report = check_sufficiency(instance, CohortScheme(soh_band_width=1.0))
    assert not report.sufficient
    assert any(issue.issue_type == "admissibility" for issue in report.issues)


def test_cohort_sufficiency_checks_deferral_and_pathway_capacity_use():
    assets = (
        Asset("A", 0.8, "NMC", 0, 50, 300),
        Asset("B", 0.8, "NMC", 0, 50, 300),
    )
    pathway = PathwaySpec("process", "Process", capacity=2)
    coefficients = {
        ("A", "process"): PairCoefficients(
            "A", "process", True, 5, 5, pathway_capacity_use=1
        ),
        ("B", "process"): PairCoefficients(
            "B", "process", True, 5, 5, pathway_capacity_use=2
        ),
    }
    instance = StaticAllocationInstance(
        assets, (pathway,), (), coefficients, {"A": 0, "B": 10}
    )
    report = check_sufficiency(instance, CohortScheme(soh_band_width=None))
    issue_types = {issue.issue_type for issue in report.issues}
    assert not report.sufficient
    assert {"deferral_cost", "pathway_capacity_use"} <= issue_types


def test_lossy_cohort_lift_enforces_original_emissions_floor():
    assets = (
        Asset("green", 0.8, "NMC", 0, 50, 300),
        Asset("valuable", 0.8, "NMC", 0, 50, 300),
    )
    pathway = PathwaySpec("process", "Process", capacity=1)
    coefficients = {
        ("green", "process"): PairCoefficients("green", "process", True, 0, 10),
        ("valuable", "process"): PairCoefficients("valuable", "process", True, 100, 0),
    }
    instance = StaticAllocationInstance(
        assets,
        (pathway,),
        (),
        coefficients,
        {"green": 0, "valuable": 0},
        co2_floor_kg=5,
    )
    result = solve_aggregated(
        instance,
        CohortScheme(soh_band_width=None),
        allow_lossy=True,
    )
    assert result.status == "Optimal"
    assert result.lifted_evaluation is not None
    assert result.lifted_evaluation.feasible
    assert result.lifted_evaluation.avoided_co2_kg >= 5
    assert result.lifted_action.assignments == {"green": "process", "valuable": None}


def test_generation_protocol_and_reduction_suite_are_deterministic():
    assert generate_fleet(size=10, seed=7) == generate_fleet(size=10, seed=7)
    assert generate_fleet(size=10, seed=7) != generate_fleet(size=10, seed=8)
    instance = default_instance(size=12, seed=7, repurpose_capacity=5, test_bay_capacity=6)
    policy = MyopicMILPPolicy(fixed_instance_builder(instance))
    assert isinstance(policy, Policy)
    decision = policy.decide(FleetState(instance.assets), DecisionContext())
    direct = solve_milp(instance)
    assert decision.action == direct.action
    changed_assets = (replace(instance.assets[0], soh=0.1), *instance.assets[1:])
    with pytest.raises(ValueError, match="complete unchanged"):
        fixed_instance_builder(instance)(FleetState(changed_assets), DecisionContext())
    report = run_reduction_checks(instance)
    assert report.passed, [(failure.name, failure.detail) for failure in report.failures]
