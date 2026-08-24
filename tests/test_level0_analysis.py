from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from dss.domain import Asset, PairCoefficients, PathwaySpec, ResourceSpec
from level0.analysis import (
    build_manifest,
    capacity_sweep_table,
    emissions_frontier_table,
    policy_comparison_table,
    run_analysis,
    write_analysis_outputs,
)
from level0.instance import StaticAllocationInstance
from level0.model import solve_milp
from scripts.visualizations.plot_level0_results import _cohort_tradeoff, create_figures


def test_capacity_policy_and_emissions_tables(scarcity_instance, emissions_instance):
    sweep = capacity_sweep_table(scarcity_instance, capacities=[0, 1, 2, 3])
    assert sweep["milp_objective"].tolist() == pytest.approx([13, 21, 22, 22])
    assert sweep["integer_use"].tolist() == pytest.approx([0, 1, 2, 2])
    assert sweep["integer_slack"].tolist() == pytest.approx([0, 0, 0, 1])
    assert sweep.loc[sweep["capacity"] == 1, "greedy_gap_percent"].item() > 0
    assert sweep.loc[sweep["capacity"] == 2, "independent_feasible"].item()

    policies = policy_comparison_table(scarcity_instance, solve_milp(scarcity_instance))
    independent = policies.set_index("policy").loc["independent_best"]
    assert independent["diagnostic_only"]
    assert not independent["feasible"]

    frontier = emissions_frontier_table(emissions_instance, points=5)
    feasible = frontier[frontier["feasible"]]
    assert feasible["economic_objective"].is_monotonic_decreasing
    assert feasible["economic_sacrifice"].is_monotonic_increasing


def test_capacity_sweep_relaxes_resources_exactly_and_requires_explicit_general_grid():
    asset = Asset("A", 0.8, "NMC", 0, 50, 300)
    pathway = PathwaySpec("repurpose", "Repurpose", capacity=1)
    resource = ResourceSpec("machine", "Machine", 0)
    unit_instance = StaticAllocationInstance(
        (asset,),
        (pathway,),
        (resource,),
        {
            ("A", "repurpose"): PairCoefficients(
                "A", "repurpose", True, 10, 0, resource_use={"machine": 100}
            )
        },
        {"A": 0},
    )
    sweep = capacity_sweep_table(unit_instance, capacities=[0, 1])
    assert sweep["milp_objective"].tolist() == pytest.approx([0, 10])
    default_sweep = capacity_sweep_table(unit_instance)
    assert default_sweep["capacity"].tolist() == pytest.approx([0, 1, 2])
    assert default_sweep["integer_slack"].iloc[-1] == pytest.approx(1)

    general_instance = replace(
        unit_instance,
        coefficients={
            ("A", "repurpose"): PairCoefficients(
                "A",
                "repurpose",
                True,
                10,
                0,
                pathway_capacity_use=2,
                resource_use={"machine": 100},
            )
        },
    )
    with pytest.raises(ValueError, match="explicit capacities"):
        capacity_sweep_table(general_instance)
    explicit = capacity_sweep_table(general_instance, capacities=[0, 2])
    assert explicit["milp_objective"].tolist() == pytest.approx([0, 10])


def test_manifest_hashes_all_model_inputs_and_solver_options(scarcity_instance):
    baseline = build_manifest(scarcity_instance)
    coefficients = dict(scarcity_instance.coefficients)
    key = ("H", "repurpose")
    coefficients[key] = replace(
        coefficients[key], economic_value=coefficients[key].economic_value + 1
    )
    changed_coefficients = build_manifest(
        replace(scarcity_instance, coefficients=coefficients)
    )
    deferral_costs = dict(scarcity_instance.deferral_costs)
    deferral_costs["H"] += 1
    changed_deferral = build_manifest(
        replace(scarcity_instance, deferral_costs=deferral_costs)
    )
    assert baseline["fleet_sha256"] == changed_coefficients["fleet_sha256"]
    assert baseline["model_inputs_sha256"] != changed_coefficients["model_inputs_sha256"]
    assert baseline["configuration_sha256"] != changed_coefficients["configuration_sha256"]
    assert baseline["model_inputs_sha256"] != changed_deferral["model_inputs_sha256"]
    assert baseline["solver_options"]["random_seed"] > 0
    assert len(baseline["cbc_cli_options"]) == 2


def test_cohort_figure_marks_unavailable_lift_as_na():
    figure = _cohort_tradeoff(
        pd.DataFrame(
            {
                "scheme": ["available", "failed"],
                "lifted_gap_percent": [1.5, float("nan")],
            }
        )
    )
    axis = figure.axes[0]
    assert len(axis.patches) == 1
    assert any("NA" in label.get_text() for label in axis.texts)
    figure.clear()


def test_evidence_pipeline_writes_stable_tables_and_figures(tmp_path, scarcity_instance):
    first = run_analysis(scarcity_instance)
    second = run_analysis(scarcity_instance)
    for name in first.tables:
        pd.testing.assert_frame_equal(first.tables[name], second.tables[name])

    results = write_analysis_outputs(first, output_dir=tmp_path / "results")
    figures = create_figures(first, figure_dir=tmp_path / "figures")
    expected_tables = {
        "asset_allocations",
        "binding_structure",
        "capacity_sweep",
        "cohort_analysis",
        "emissions_frontier",
        "policy_comparison",
        "analysis_summary",
        "run_manifest",
    }
    assert set(results) == expected_tables
    assert len(figures) == 6
    for path in results.values():
        assert Path(path).exists() and Path(path).stat().st_size > 0
    for png, pdf in figures.values():
        assert png.read_bytes().startswith(b"\x89PNG")
        assert pdf.read_bytes().startswith(b"%PDF")
        assert png.stat().st_size > 1_000
        assert pdf.stat().st_size > 1_000
