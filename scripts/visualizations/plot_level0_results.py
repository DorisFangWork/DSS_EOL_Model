"""Regenerate Level 0 tidy tables and thesis-ready PNG/PDF figures."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from types import MappingProxyType
from typing import Mapping

# Preserve the handover command `python scripts/visualizations/plot_level0_results.py`
# without requiring an editable install first.
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from level0.analysis import AnalysisBundle, PROJECT_ROOT, run_analysis, write_analysis_outputs


COLORS = {
    "repurpose": "#2A9D8F",
    "recycle": "#457B9D",
    "defer": "#E76F51",
}


def _save(fig: plt.Figure, destination: Path, name: str) -> tuple[Path, Path]:
    destination.mkdir(parents=True, exist_ok=True)
    png = destination / f"{name}.png"
    pdf = destination / f"{name}.pdf"
    fig.savefig(png, dpi=220, bbox_inches="tight")
    fig.savefig(pdf, bbox_inches="tight", metadata={"Creator": "PhD DSS prototype"})
    plt.close(fig)
    return png, pdf


def _asset_allocations(table: pd.DataFrame) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(8.2, 5.0))
    for decision, group in table.groupby("decision", sort=True):
        ax.scatter(
            group["soh"],
            group["economic_contribution"],
            label=decision,
            color=COLORS.get(decision, "#666666"),
            alpha=0.8,
            edgecolor="white",
            linewidth=0.4,
        )
    ax.set_xlabel("State of health")
    ax.set_ylabel("Economic contribution (SGD)")
    ax.set_title("Asset-level Level 0 allocation")
    ax.legend(frameon=False)
    ax.grid(alpha=0.2)
    return fig


def _binding_structure(table: pd.DataFrame) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    labels = table["entity_id"].tolist()
    x = range(len(labels))
    ax.bar(x, table["rhs"], color="#D9E2EC", label="capacity / requirement")
    ax.bar(x, table["integer_use"], color="#2A9D8F", label="integer solution use")
    ax.set_xticks(list(x), labels, rotation=20, ha="right")
    ax.set_ylabel("Resource units")
    ax.set_title("Capacity use and geometric binding")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.2)
    return fig


def _capacity_boundary(table: pd.DataFrame) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(8.2, 5.0))
    ax.plot(table["capacity"], table["milp_objective"], marker="o", color="#264653")
    ax.set_xlabel("Repurposing capacity (packs)")
    ax.set_ylabel("MILP economic objective (SGD)", color="#264653")
    ax.tick_params(axis="y", labelcolor="#264653")
    second = ax.twinx()
    second.plot(
        table["capacity"],
        table["lp_marginal_value"],
        marker="s",
        color="#E76F51",
        alpha=0.8,
    )
    second.set_ylabel("LP marginal capacity value (SGD/pack)", color="#E76F51")
    second.tick_params(axis="y", labelcolor="#E76F51")
    ax.set_title("Capacity boundary: performance and marginal value")
    ax.grid(alpha=0.2)
    return fig


def _cohort_tradeoff(table: pd.DataFrame) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    plot = table.copy()
    positions = list(range(len(plot)))
    available = plot["lifted_gap_percent"].notna()
    available_positions = [
        position for position, present in zip(positions, available) if present
    ]
    available_values = plot.loc[available, "lifted_gap_percent"].tolist()
    ax.bar(available_positions, available_values, color="#457B9D")
    for position, present in zip(positions, available):
        if not present:
            ax.text(position, 0, "NA\n(no implementable lift)", ha="center", va="bottom")
    ax.set_xticks(positions, plot["scheme"], rotation=20)
    ax.set_ylabel("Implementable value loss (%)")
    ax.set_xlabel("Cohort scheme")
    ax.set_title("Measured cost of cohort aggregation")
    ax.grid(axis="y", alpha=0.2)
    return fig


def _emissions_frontier(table: pd.DataFrame) -> plt.Figure:
    feasible = table[table["feasible"]].copy()
    fig, ax = plt.subplots(figsize=(8.2, 5.0))
    ax.plot(
        feasible["achieved_co2_kg"],
        feasible["economic_sacrifice"],
        marker="o",
        color="#2A9D8F",
    )
    ax.set_xlabel("Achieved avoided emissions (kg CO2e)")
    ax.set_ylabel("Economic sacrifice from value optimum (SGD)")
    ax.set_title("Economic-environmental constraint frontier")
    ax.grid(alpha=0.2)
    return fig


def _policy_comparison(table: pd.DataFrame) -> plt.Figure:
    plot = table[table["feasible"]].copy()
    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    ax.bar(plot["policy"], plot["economic_objective"], color="#264653")
    ax.set_ylabel("Economic objective (SGD)")
    ax.set_title("Exact Level 0 benchmark versus feasible policies")
    ax.tick_params(axis="x", rotation=20)
    ax.grid(axis="y", alpha=0.2)
    return fig


def create_figures(
    bundle: AnalysisBundle,
    *,
    figure_dir: Path | str | None = None,
) -> Mapping[str, tuple[Path, Path]]:
    destination = Path(figure_dir) if figure_dir else PROJECT_ROOT / "figures" / "level0"
    builders = {
        "asset_allocations": _asset_allocations,
        "binding_structure": _binding_structure,
        "capacity_boundary": lambda _: _capacity_boundary(bundle.tables["capacity_sweep"]),
        "cohort_tradeoff": lambda _: _cohort_tradeoff(bundle.tables["cohort_analysis"]),
        "emissions_frontier": _emissions_frontier,
        "policy_comparison": _policy_comparison,
    }
    source_tables = {
        "asset_allocations": "asset_allocations",
        "binding_structure": "binding_structure",
        "capacity_boundary": "capacity_sweep",
        "cohort_tradeoff": "cohort_analysis",
        "emissions_frontier": "emissions_frontier",
        "policy_comparison": "policy_comparison",
    }
    paths: dict[str, tuple[Path, Path]] = {}
    for name, builder in builders.items():
        figure = builder(bundle.tables[source_tables[name]])
        paths[name] = _save(figure, destination, name)
    return MappingProxyType(paths)


def generate_evidence(
    *,
    output_dir: Path | str | None = None,
    figure_dir: Path | str | None = None,
) -> tuple[Mapping[str, Path], Mapping[str, tuple[Path, Path]]]:
    bundle = run_analysis()
    table_paths = write_analysis_outputs(bundle, output_dir=output_dir)
    figure_paths = create_figures(bundle, figure_dir=figure_dir)
    return table_paths, figure_paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=None)
    parser.add_argument("--figures-dir", type=Path, default=None)
    args = parser.parse_args()
    table_paths, figure_paths = generate_evidence(
        output_dir=args.results_dir,
        figure_dir=args.figures_dir,
    )
    print(f"Wrote {len(table_paths)} tables/documents and {2 * len(figure_paths)} figures.")


if __name__ == "__main__":
    main()
