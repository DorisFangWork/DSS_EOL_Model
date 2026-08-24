"""Reproducible tidy analysis tables for Level 0 research evidence."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping

import numpy as np
import pandas as pd
import pulp

from .cohorts import CohortScheme, check_sufficiency, solve_aggregated
from .evaluation import evaluate_action
from .instance import StaticAllocationInstance, default_instance
from .model import (
    RelaxationResult,
    SolveResult,
    SolverOptions,
    solve_emissions_endpoint,
    solve_lp_relaxation,
    solve_milp,
)
from .policies import fifo, greedy_value, independent_best, policy_gap_percent, soh_threshold
from .verify import run_reduction_checks


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class AnalysisBundle:
    instance: StaticAllocationInstance
    tables: Mapping[str, pd.DataFrame]
    summary_markdown: str
    manifest: Mapping[str, object]


def _require_optimal(result: SolveResult) -> SolveResult:
    if not result.optimal or result.action is None or result.evaluation is None:
        raise RuntimeError(f"expected optimal solve, received {result.status}")
    return result


def asset_allocations_table(
    instance: StaticAllocationInstance, result: SolveResult
) -> pd.DataFrame:
    result = _require_optimal(result)
    assert result.action is not None
    rows: list[dict[str, object]] = []
    for asset in sorted(instance.assets, key=lambda item: item.asset_id):
        pathway_id = result.action.assignments[asset.asset_id]
        coefficient = (
            instance.coefficients[(asset.asset_id, pathway_id)]
            if pathway_id is not None
            else None
        )
        rows.append(
            {
                "scenario": instance.scenario_label,
                "asset_id": asset.asset_id,
                "soh": asset.soh,
                "chemistry": asset.chemistry,
                "safety_class": asset.safety_class,
                "nameplate_kwh": asset.nameplate_kwh,
                "usable_kwh": asset.usable_kwh,
                "mass_kg": asset.mass_kg,
                "periods_held": asset.periods_held,
                "decision": pathway_id or "defer",
                "economic_contribution": (
                    coefficient.economic_value
                    if coefficient is not None
                    else -instance.deferral_costs[asset.asset_id]
                ),
                "avoided_co2_kg": coefficient.avoided_co2_kg if coefficient else 0.0,
            }
        )
    return pd.DataFrame(rows).sort_values("asset_id", kind="stable").reset_index(drop=True)


def _shadow_by_entity(
    relaxation: RelaxationResult, kind: str, entity_id: str
):
    return next(
        (
            shadow
            for shadow in relaxation.shadow_prices.values()
            if shadow.constraint_kind == kind and shadow.entity_id == entity_id
        ),
        None,
    )


def binding_structure_table(
    instance: StaticAllocationInstance,
    result: SolveResult,
    relaxation: RelaxationResult,
) -> pd.DataFrame:
    result = _require_optimal(result)
    assert result.evaluation is not None
    rows: list[dict[str, object]] = []
    for pathway in instance.pathways:
        if pathway.capacity is None:
            continue
        use = result.evaluation.pathway_use[pathway.pathway_id]
        shadow = _shadow_by_entity(relaxation, "pathway_capacity", pathway.pathway_id)
        rows.append(
            {
                "constraint_kind": "pathway_capacity",
                "entity_id": pathway.pathway_id,
                "rhs": pathway.capacity,
                "integer_use": use,
                "integer_slack": pathway.capacity - use,
                "integer_binding": abs(pathway.capacity - use) <= 1e-7,
                "lp_use": shadow.use if shadow else np.nan,
                "lp_slack": shadow.slack if shadow else np.nan,
                "lp_binding": shadow.binding if shadow else False,
                "lp_marginal_value": shadow.marginal_value if shadow else np.nan,
                "dual_source": shadow.source if shadow else None,
            }
        )
    for resource in instance.resources:
        use = result.evaluation.resource_use[resource.resource_id]
        shadow = _shadow_by_entity(relaxation, "resource_capacity", resource.resource_id)
        rows.append(
            {
                "constraint_kind": "resource_capacity",
                "entity_id": resource.resource_id,
                "rhs": resource.capacity,
                "integer_use": use,
                "integer_slack": resource.capacity - use,
                "integer_binding": abs(resource.capacity - use) <= 1e-7,
                "lp_use": shadow.use if shadow else np.nan,
                "lp_slack": shadow.slack if shadow else np.nan,
                "lp_binding": shadow.binding if shadow else False,
                "lp_marginal_value": shadow.marginal_value if shadow else np.nan,
                "dual_source": shadow.source if shadow else None,
            }
        )
    if instance.co2_floor_kg is not None:
        shadow = _shadow_by_entity(relaxation, "co2_floor", "avoided_co2_kg")
        use = result.evaluation.avoided_co2_kg
        rows.append(
            {
                "constraint_kind": "co2_floor",
                "entity_id": "avoided_co2_kg",
                "rhs": instance.co2_floor_kg,
                "integer_use": use,
                "integer_slack": use - instance.co2_floor_kg,
                "integer_binding": abs(use - instance.co2_floor_kg) <= 1e-7,
                "lp_use": shadow.use if shadow else np.nan,
                "lp_slack": shadow.slack if shadow else np.nan,
                "lp_binding": shadow.binding if shadow else False,
                "lp_marginal_value": shadow.marginal_value if shadow else np.nan,
                "dual_source": shadow.source if shadow else None,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["constraint_kind", "entity_id"], kind="stable"
    ).reset_index(drop=True)


def policy_comparison_table(
    instance: StaticAllocationInstance, result: SolveResult
) -> pd.DataFrame:
    result = _require_optimal(result)
    assert result.action is not None and result.evaluation is not None
    policies = [
        ("milp_optimal", result.action, False),
        ("independent_best", independent_best(instance), True),
        ("greedy_value", greedy_value(instance), False),
        ("soh_threshold_0.75", soh_threshold(instance, threshold=0.75), False),
        ("fifo", fifo(instance), False),
    ]
    rows: list[dict[str, object]] = []
    reference = result.evaluation.economic_objective
    for name, action, diagnostic_only in policies:
        evaluation = evaluate_action(instance, action)
        gap = (
            policy_gap_percent(reference, evaluation.economic_objective)
            if evaluation.feasible
            else None
        )
        rows.append(
            {
                "policy": name,
                "diagnostic_only": diagnostic_only,
                "feasible": evaluation.feasible,
                "economic_objective": evaluation.economic_objective,
                "avoided_co2_kg": evaluation.avoided_co2_kg,
                "deferred_count": evaluation.details["deferred_count"],
                "gap_from_milp_percent": gap,
                "diagnostic_excess_over_milp": (
                    evaluation.economic_objective - reference if diagnostic_only else np.nan
                ),
                "violations": " | ".join(evaluation.violations),
            }
        )
    return pd.DataFrame(rows)


def capacity_sweep_table(
    instance: StaticAllocationInstance,
    capacities: Iterable[float] | None = None,
    *,
    pathway_id: str = "repurpose",
) -> pd.DataFrame:
    if pathway_id not in instance.pathway_by_id:
        raise KeyError(pathway_id)
    admissible_capacity_uses = [
        instance.coefficients[(asset.asset_id, pathway_id)].pathway_capacity_use
        for asset in instance.assets
        if instance.coefficients[(asset.asset_id, pathway_id)].admissible
    ]
    if capacities is None:
        # Integer pack capacities expose both the exact economic boundary and the
        # first strictly slack capacity; a coarse plot grid can conceal the difference.
        if any(abs(use - 1.0) > 1e-9 for use in admissible_capacity_uses):
            raise ValueError(
                "default capacity grid requires unit pathway_capacity_use; "
                "pass explicit capacities for a general-capacity instance"
            )
        # Include one capacity unit beyond the maximum possible target-path use
        # so geometric slack is observable instead of ending the sweep at equality.
        capacities = range(0, len(admissible_capacity_uses) + 2)
    relaxed_resources = {
        resource.resource_id: sum(
            max(
                (
                    instance.coefficients[(asset.asset_id, pathway.pathway_id)]
                    .resource_use.get(resource.resource_id, 0.0)
                    for pathway in instance.pathways
                    if instance.coefficients[(asset.asset_id, pathway.pathway_id)].admissible
                ),
                default=0.0,
            )
            for asset in instance.assets
        )
        for resource in instance.resources
    }
    rows: list[dict[str, object]] = []
    for capacity in sorted({float(value) for value in capacities}):
        scenario = instance.with_capacities(
            pathway_capacities={pathway_id: capacity},
            resource_capacities=relaxed_resources,
            scenario_label=f"{instance.scenario_label}_{pathway_id}_cap_{capacity:g}",
        ).with_co2_floor(None)
        milp = _require_optimal(solve_milp(scenario))
        relaxation = solve_lp_relaxation(scenario)
        assert milp.evaluation is not None
        shadow = _shadow_by_entity(relaxation, "pathway_capacity", pathway_id)
        greedy_evaluation = evaluate_action(scenario, greedy_value(scenario))
        independent_evaluation = evaluate_action(scenario, independent_best(scenario))
        use = milp.evaluation.pathway_use[pathway_id]
        rows.append(
            {
                "pathway": pathway_id,
                "capacity": capacity,
                "milp_objective": milp.evaluation.economic_objective,
                "milp_avoided_co2_kg": milp.evaluation.avoided_co2_kg,
                "integer_use": use,
                "integer_slack": capacity - use,
                "integer_binding": abs(capacity - use) <= 1e-7,
                "lp_marginal_value": shadow.marginal_value if shadow else np.nan,
                "lp_use": shadow.use if shadow else np.nan,
                "greedy_objective": greedy_evaluation.economic_objective,
                "greedy_gap_percent": policy_gap_percent(
                    milp.evaluation.economic_objective,
                    greedy_evaluation.economic_objective,
                ),
                "independent_feasible": independent_evaluation.feasible,
                "independent_objective": independent_evaluation.economic_objective,
            }
        )
    return pd.DataFrame(rows).sort_values("capacity", kind="stable").reset_index(drop=True)


def emissions_frontier_table(
    instance: StaticAllocationInstance,
    *,
    points: int = 9,
) -> pd.DataFrame:
    if points < 2:
        raise ValueError("points must be at least 2")
    base_instance = instance.with_co2_floor(None)
    economic = _require_optimal(solve_milp(base_instance))
    emissions_endpoint = _require_optimal(solve_emissions_endpoint(base_instance))
    assert economic.evaluation is not None and emissions_endpoint.evaluation is not None
    economic_emissions = economic.evaluation.avoided_co2_kg
    maximum_emissions = emissions_endpoint.evaluation.avoided_co2_kg
    floors = np.linspace(economic_emissions, maximum_emissions, points)
    rows: list[dict[str, object]] = []
    for floor_value in floors:
        constrained = base_instance.with_co2_floor(float(floor_value))
        milp = solve_milp(constrained)
        relaxation = solve_lp_relaxation(constrained)
        if milp.optimal and milp.evaluation is not None:
            shadow = _shadow_by_entity(relaxation, "co2_floor", "avoided_co2_kg")
            rows.append(
                {
                    "co2_floor_kg": float(floor_value),
                    "feasible": True,
                    "economic_objective": milp.evaluation.economic_objective,
                    "achieved_co2_kg": milp.evaluation.avoided_co2_kg,
                    "economic_sacrifice": (
                        economic.evaluation.economic_objective
                        - milp.evaluation.economic_objective
                    ),
                    "lp_marginal_carbon_cost": shadow.marginal_value if shadow else np.nan,
                }
            )
        else:
            rows.append(
                {
                    "co2_floor_kg": float(floor_value),
                    "feasible": False,
                    "economic_objective": np.nan,
                    "achieved_co2_kg": np.nan,
                    "economic_sacrifice": np.nan,
                    "lp_marginal_carbon_cost": np.nan,
                }
            )
    return pd.DataFrame(rows).sort_values("co2_floor_kg", kind="stable").reset_index(drop=True)


def cohort_analysis_table(instance: StaticAllocationInstance) -> pd.DataFrame:
    schemes = [
        ("singleton", CohortScheme(soh_band_width=None, include_asset_id=True)),
        ("soh_0.01", CohortScheme(soh_band_width=0.01)),
        ("soh_0.05", CohortScheme(soh_band_width=0.05)),
        ("soh_0.10", CohortScheme(soh_band_width=0.10)),
        ("ignore_soh", CohortScheme(soh_band_width=None)),
    ]
    rows: list[dict[str, object]] = []
    for name, scheme in schemes:
        sufficiency = check_sufficiency(instance, scheme)
        result = solve_aggregated(instance.with_co2_floor(None), scheme, allow_lossy=True)
        rows.append(
            {
                "scheme": name,
                "cohort_count": result.group_count,
                "sufficient": sufficiency.sufficient,
                "sufficiency_issue_count": len(sufficiency.issues),
                "representative_objective": result.representative_objective,
                "lifted_objective": (
                    result.lifted_evaluation.economic_objective
                    if result.lifted_evaluation is not None
                    else np.nan
                ),
                "asset_optimal_objective": result.asset_optimal_objective,
                "representative_gap": result.representative_gap,
                "lifted_gap": result.lifted_gap,
                "lifted_gap_percent": result.lifted_gap_percent,
                "lifted_feasible": (
                    result.lifted_evaluation.feasible
                    if result.lifted_evaluation is not None
                    else False
                ),
            }
        )
    return pd.DataFrame(rows)


def _package_version(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def _cbc_metadata() -> dict[str, object]:
    path = str(pulp.PULP_CBC_CMD.pulp_cbc_path)
    output: str | None = None
    try:
        completed = subprocess.run(
            [path, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        lines = (completed.stdout or completed.stderr).strip().splitlines()
        output = next(
            (line.split(":", 1)[1].strip() for line in lines if line.startswith("Version:")),
            lines[0] if lines else None,
        )
    except (OSError, subprocess.SubprocessError, IndexError):
        output = None
    return {"path": path, "version_output": output}


def _scenario_fingerprint(instance: StaticAllocationInstance) -> str:
    rows = [
        (
            asset.asset_id,
            asset.soh,
            asset.chemistry,
            asset.safety_class,
            asset.nameplate_kwh,
            asset.mass_kg,
            asset.periods_held,
        )
        for asset in instance.assets
    ]
    payload = json.dumps(rows, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _jsonable(value):
    if is_dataclass(value):
        return {item.name: _jsonable(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _model_input_payload(instance: StaticAllocationInstance) -> dict[str, object]:
    """Canonicalize every quantity that can change the mathematical model."""

    return {
        "assets": [
            _jsonable(asset) for asset in sorted(instance.assets, key=lambda item: item.asset_id)
        ],
        "pathways": [
            _jsonable(pathway)
            for pathway in sorted(instance.pathways, key=lambda item: item.pathway_id)
        ],
        "resources": [
            _jsonable(resource)
            for resource in sorted(instance.resources, key=lambda item: item.resource_id)
        ],
        "coefficients": [
            _jsonable(instance.coefficients[key]) for key in sorted(instance.coefficients)
        ],
        "deferral_costs": [
            {"asset_id": asset_id, "cost": instance.deferral_costs[asset_id]}
            for asset_id in sorted(instance.deferral_costs)
        ],
        "co2_floor_kg": instance.co2_floor_kg,
    }


def _sha256_json(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _git_metadata() -> dict[str, object]:
    try:
        commit = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        status = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return {
            "commit": commit.stdout.strip() if commit.returncode == 0 else None,
            "dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
        }
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def build_manifest(
    instance: StaticAllocationInstance,
    solver_options: SolverOptions | None = None,
) -> dict[str, object]:
    options = solver_options or SolverOptions()
    scenario_parameters = {
        "pathways": [_jsonable(pathway) for pathway in instance.pathways],
        "resources": [_jsonable(resource) for resource in instance.resources],
        "valuation": _jsonable(instance.metadata.get("valuation")),
        "co2_floor_kg": instance.co2_floor_kg,
    }
    model_inputs = _model_input_payload(instance)
    solver_parameters = _jsonable(options)
    configuration = {
        "model_inputs": model_inputs,
        "solver_options": solver_parameters,
    }
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scenario_label": instance.scenario_label,
        "seed": instance.metadata.get("seed"),
        "data_kind": instance.metadata.get("data_kind"),
        "fleet_size": len(instance.assets),
        "fleet_sha256": _scenario_fingerprint(instance),
        "model_inputs_sha256": _sha256_json(model_inputs),
        "configuration_sha256": _sha256_json(configuration),
        "scenario_parameters": scenario_parameters,
        "python": sys.version,
        "platform": platform.platform(),
        "packages": {
            package: _package_version(package)
            for package in ("pulp", "numpy", "pandas", "matplotlib", "pytest")
        },
        "solver": _cbc_metadata(),
        "solver_options": solver_parameters,
        "cbc_cli_options": [
            f"randomSeed {options.random_seed}",
            f"randomCbcSeed {options.random_seed}",
        ],
        "git": _git_metadata(),
        "units": instance.metadata.get(
            "units",
            {
                "currency": instance.metadata.get("currency", "SGD"),
                "emissions": instance.metadata.get("co2_unit", "kg CO2e"),
            },
        ),
        "interpretation": instance.metadata.get(
            "interpretation",
            "synthetic mechanism evidence; not an OEM prediction",
        ),
    }


def _summary(
    instance: StaticAllocationInstance,
    result: SolveResult,
    tables: Mapping[str, pd.DataFrame],
) -> str:
    result = _require_optimal(result)
    assert result.evaluation is not None
    verification = run_reduction_checks(instance)
    policy = tables["policy_comparison"].set_index("policy")
    sweep = tables["capacity_sweep"]
    economic_boundary_rows = sweep[sweep["independent_feasible"]]
    economic_boundary = (
        economic_boundary_rows.iloc[0]["capacity"] if not economic_boundary_rows.empty else None
    )
    strict_slack_rows = sweep[sweep["integer_slack"] > 1e-7]
    strict_slack = strict_slack_rows.iloc[0]["capacity"] if not strict_slack_rows.empty else None
    peak_gap_row = sweep.loc[sweep["greedy_gap_percent"].idxmax()]
    economic_boundary_text = (
        "not observed" if economic_boundary is None else f"{economic_boundary:g} packs"
    )
    strict_slack_text = "not observed" if strict_slack is None else f"{strict_slack:g} packs"
    return "\n".join(
        [
            "# Level 0 analysis summary",
            "",
            "> Synthetic illustrative scenario: mechanism evidence, not an OEM prediction.",
            "",
            f"- Scenario: `{instance.scenario_label}`",
            f"- Fleet size: {len(instance.assets)} packs",
            f"- MILP economic objective: {result.evaluation.economic_objective:,.2f} SGD",
            f"- Avoided emissions: {result.evaluation.avoided_co2_kg:,.2f} kg CO2e",
            f"- Deferred assets: {result.evaluation.details['deferred_count']}",
            f"- Greedy gap: {policy.loc['greedy_value', 'gap_from_milp_percent']:.2f}%",
            f"- Independent-choice capacity boundary: {economic_boundary_text}",
            f"- First strictly slack integer capacity: {strict_slack_text}",
            f"- Largest greedy gap in sweep: {peak_gap_row['greedy_gap_percent']:.2f}% "
            f"at capacity {peak_gap_row['capacity']:g}",
            f"- Verification checks: {sum(c.passed for c in verification.checks)}/{len(verification.checks)} passed",
            "",
            "The capacity sweep distinguishes geometric binding (zero slack) from",
            "economic scarcity (positive LP marginal value). Cohort results report",
            "the implementable lifted-action loss, not only the representative model value.",
            "",
        ]
    )


def run_analysis(instance: StaticAllocationInstance | None = None) -> AnalysisBundle:
    scenario = instance or default_instance()
    milp = _require_optimal(solve_milp(scenario))
    relaxation = solve_lp_relaxation(scenario)
    tables: dict[str, pd.DataFrame] = {
        "asset_allocations": asset_allocations_table(scenario, milp),
        "binding_structure": binding_structure_table(scenario, milp, relaxation),
        "capacity_sweep": capacity_sweep_table(scenario),
        "cohort_analysis": cohort_analysis_table(scenario),
        "emissions_frontier": emissions_frontier_table(scenario),
        "policy_comparison": policy_comparison_table(scenario, milp),
    }
    return AnalysisBundle(
        instance=scenario,
        tables=MappingProxyType(tables),
        summary_markdown=_summary(scenario, milp, tables),
        manifest=MappingProxyType(build_manifest(scenario)),
    )


def write_analysis_outputs(
    bundle: AnalysisBundle | None = None,
    *,
    output_dir: Path | str | None = None,
) -> Mapping[str, Path]:
    analysis = bundle or run_analysis()
    destination = Path(output_dir) if output_dir else PROJECT_ROOT / "results" / "level0"
    destination.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name, table in analysis.tables.items():
        path = destination / f"{name}.csv"
        table.to_csv(path, index=False, encoding="utf-8", float_format="%.10g")
        paths[name] = path
    summary_path = destination / "analysis_summary.md"
    summary_path.write_text(analysis.summary_markdown, encoding="utf-8")
    paths["analysis_summary"] = summary_path
    manifest_path = destination / "run_manifest.json"
    manifest_path.write_text(
        json.dumps(dict(analysis.manifest), indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    paths["run_manifest"] = manifest_path
    return MappingProxyType(paths)
