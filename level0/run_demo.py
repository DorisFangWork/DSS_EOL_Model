"""Readable narrative demonstration of the reconstructed Level 0 model."""

from __future__ import annotations

import argparse
from pathlib import Path

from .evaluation import evaluate_action
from .instance import default_instance
from .model import available_solvers, solve_lp_relaxation, solve_milp
from .policies import fifo, greedy_value, independent_best, policy_gap_percent, soh_threshold
from .verify import run_reduction_checks


def _render() -> str:
    instance = default_instance()
    milp = solve_milp(instance)
    if not milp.optimal or milp.action is None or milp.evaluation is None:
        raise RuntimeError(f"Level 0 demo failed: {milp.status}")
    relaxation = solve_lp_relaxation(instance)
    verification = run_reduction_checks(instance)
    pathway_counts = milp.evaluation.details["pathway_counts"]

    lines = [
        "Level 0 - static asset-informed fleet allocation",
        "=" * 51,
        "Synthetic illustrative data; not an OEM forecast.",
        "",
        f"Scenario: {instance.scenario_label}",
        f"Assets: {len(instance.assets)}",
        f"Available solvers: {', '.join(available_solvers()) or 'none'}",
        f"MILP status: {milp.status}",
        f"Economic objective: SGD {milp.evaluation.economic_objective:,.2f}",
        f"Avoided emissions: {milp.evaluation.avoided_co2_kg:,.2f} kg CO2e",
        f"Pathway counts: {dict(pathway_counts)}",
        f"Deferred: {milp.evaluation.details['deferred_count']}",
        "",
        "LP relaxation and scarcity",
        "-" * 28,
        f"LP objective upper bound: SGD {relaxation.economic_objective:,.2f}",
    ]
    for shadow in relaxation.shadow_prices.values():
        lines.append(
            f"{shadow.constraint_kind}:{shadow.entity_id} - use={shadow.use:.2f}, "
            f"rhs={shadow.rhs:.2f}, slack={shadow.slack:.2f}, "
            f"marginal value={shadow.marginal_value:,.2f}"
        )

    lines.extend(["", "Policy comparison", "-" * 17])
    policy_actions = [
        ("independent_best (diagnostic)", independent_best(instance)),
        ("greedy_value", greedy_value(instance)),
        ("soh_threshold_0.75", soh_threshold(instance)),
        ("fifo", fifo(instance)),
    ]
    for name, action in policy_actions:
        evaluation = evaluate_action(instance, action)
        gap = (
            policy_gap_percent(
                milp.evaluation.economic_objective, evaluation.economic_objective
            )
            if evaluation.feasible
            else None
        )
        gap_text = f", gap={gap:.2f}%" if gap is not None else ""
        lines.append(
            f"{name}: feasible={evaluation.feasible}, "
            f"objective=SGD {evaluation.economic_objective:,.2f}{gap_text}"
        )

    lines.extend(
        [
            "",
            "Verification",
            "-" * 12,
            f"{sum(check.passed for check in verification.checks)}/"
            f"{len(verification.checks)} checks passed",
        ]
    )
    for check in verification.failures:
        lines.append(f"FAIL {check.name}: {check.detail}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    rendered = _render()
    print(rendered, end="")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
