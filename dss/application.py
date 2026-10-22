"""Independent and integrated capability execution with reproducible run snapshots."""

from datetime import datetime, timezone
import hashlib
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
from uuid import uuid4

from . import admissibility, destination, flow
from .admissibility import Eligibility, validate_eligibility
from .serialization import fingerprint, plain


MODES = ("admission", "destination", "allocation", "integrated")


def eligibility_evidence(scenario, records=None):
    records = admissibility.assess_scenario(scenario) if records is None else records
    return {"schema_version": 1, "scenario_fingerprint": fingerprint(scenario),
            "records": plain(validate_eligibility(scenario, records))}


def read_evidence(scenario, evidence):
    if not isinstance(evidence, dict) or set(evidence) != {"schema_version", "scenario_fingerprint", "records"}:
        raise ValueError("invalid eligibility evidence envelope")
    if evidence["schema_version"] != 1 or evidence["scenario_fingerprint"] != fingerprint(scenario):
        raise ValueError("eligibility evidence belongs to a different scenario version or input snapshot")
    try:
        return validate_eligibility(scenario, (Eligibility(**row) for row in evidence["records"]))
    except (TypeError, KeyError, AttributeError) as error:
        raise ValueError(f"invalid eligibility evidence: {error}") from error


def implementation_record():
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for folder in ("dss", "level0"):
        for path in sorted((root / folder).glob("*.py")):
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    packages = {}
    for package in ("pulp", "numpy", "pandas", "streamlit"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = "not installed"
    return {"application_version": "modular-dss/1", "core_source_sha256": digest.hexdigest(),
            "packages": packages}


def run(scenario, mode="integrated", *, supplied_eligibility=None,
        criterion="economic_value", unknown_policy="reject"):
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if unknown_policy not in {"reject", "exclude"}:
        raise ValueError("unknown_policy must be reject or exclude")
    if mode == "admission" and supplied_eligibility is not None:
        raise ValueError("admission mode evaluates configured rules; omit supplied evidence")
    if mode == "allocation" and supplied_eligibility is None:
        raise ValueError("allocation-only mode requires supplied eligibility evidence")
    records = (read_evidence(scenario, supplied_eligibility) if supplied_eligibility is not None
               else admissibility.assess_scenario(scenario))
    output = {
        "schema_version": 1, "run_id": str(uuid4()),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "scenario": plain(scenario), "scenario_fingerprint": fingerprint(scenario),
        "implementation": implementation_record(), "mode": mode,
        "criterion": criterion if mode in {"destination", "integrated"} else None,
        "unknown_policy": unknown_policy, "eligibility_origin": "supplied" if supplied_eligibility is not None else "configured rules",
        "eligibility": plain(records), "status": "completed", "comparisons": [],
        "allocation": None, "evaluation": None, "solver": None, "decision_reasons": [],
    }
    if mode in {"allocation", "integrated"}:
        result, report = flow.allocate(scenario, records, unknown_policy)
        output.update(status=result.status, allocation=plain(result.action),
                      evaluation=plain(report), solver=plain(result.diagnostics))
        if result.action is not None:
            values = {(v.asset_id, v.pathway_id): v for v in scenario.values}
            for asset_id, chosen in result.action.assignments.items():
                eligible = [r.pathway_id for r in records if r.asset_id == asset_id and r.status == "eligible"]
                best = max((values[(asset_id, p)].economic_value for p in eligible), default=None)
                if chosen is None:
                    explanation = ("No eligible represented destination; deferred at the stated current-period cost."
                                   if not eligible else "Deferral selected within the portfolio optimum, including costs and shared constraints.")
                elif values[(asset_id, chosen)].economic_value < best:
                    explanation = "Selected within the portfolio optimum despite a higher-valued individual alternative; inspect shared limits and the full allocation."
                else:
                    explanation = "An individually highest-valued eligible destination, selected within the portfolio optimum."
                output["decision_reasons"].append({"asset_id": asset_id, "chosen": chosen,
                    "eligible_destinations": eligible, "explanation": explanation})
    if mode in {"destination", "integrated"}:
        # Explanatory comparison is not an input to the optimiser.
        output["comparisons"] = plain(destination.compare(scenario, records, criterion))
    return output


def compare_runs(first, second):
    """Raw differences, never a causal gain or a claim that different modes are equivalent."""
    changed = [key for key in sorted(set(first["scenario"]) | set(second["scenario"]))
               if first["scenario"].get(key) != second["scenario"].get(key)]
    setting_changes = [key for key in ("mode", "criterion", "unknown_policy", "eligibility_origin", "eligibility", "implementation")
                       if first.get(key) != second.get(key)]
    result = {"changed_scenario_fields": changed, "changed_run_fields": setting_changes,
              "interpretation": "Descriptive comparison of saved runs; differences do not identify a causal effect.",
              "differences": {}}
    a, b = first.get("evaluation"), second.get("evaluation")
    if a and b and first["scenario"]["currency"] == second["scenario"]["currency"] and first["scenario"]["horizon"] == second["scenario"]["horizon"] and first["scenario"]["periods"] == second["scenario"]["periods"]:
        result["differences"] = {key: b[key] - a[key] for key in ("economic_objective", "avoided_co2_kg")}
    else:
        result["interpretation"] += " Numeric differences omitted: evaluated allocations and matching currency/horizon are required."
    return result
