from dataclasses import replace
import json
from pathlib import Path
import sqlite3

import pytest

from dss import admissibility, destination, flow
from dss.admissibility import Eligibility
from dss.application import compare_runs, eligibility_evidence, run
from dss.domain import PathwaySpec
from dss.planning import BatteryRecord, OptionValue
from dss.serialization import batteries_from_csv, fingerprint, plain, scenario_from_json, scenario_json
from dss.storage import RunStore

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def scenario():
    return scenario_from_json((ROOT / "configs/dss/scarcity.json").read_text())


def test_independent_modes_do_not_call_allocator(monkeypatch, scenario):
    def forbidden(*args, **kwargs):
        pytest.fail("independent capability called allocation")
    monkeypatch.setattr(flow, "allocate", forbidden)
    admission = run(replace(scenario, values=(), deferral_costs={}), "admission")
    assert {r["status"] for r in admission["eligibility"]} == {"eligible"}
    comparison = run(scenario, "destination")
    assert {r["pathway_id"] for r in comparison["comparisons"] if r["preferred"]} == {"repurpose"}
    assert comparison["allocation"] is None


def test_allocation_only_uses_supplied_evidence(monkeypatch, scenario):
    evidence = eligibility_evidence(scenario)
    def forbidden(*args, **kwargs):
        pytest.fail("allocation-only recomputed admission or rankings")
    monkeypatch.setattr(admissibility, "assess_scenario", forbidden)
    monkeypatch.setattr(destination, "compare", forbidden)
    result = run(scenario, "allocation", supplied_eligibility=evidence)
    assert result["allocation"]["assignments"] == {"A": "recycle", "B": "repurpose"}
    assert result["evaluation"]["economic_objective"] == 17


def test_joint_choice_not_fixed_by_individual_rankings(scenario):
    result = run(scenario)
    preferred = {r["asset_id"]: r["pathway_id"] for r in result["comparisons"] if r["preferred"]}
    assert preferred == {"A": "repurpose", "B": "repurpose"}
    assert result["allocation"]["assignments"] == {"A": "recycle", "B": "repurpose"}
    assert result["evaluation"]["feasible"]
    assert run(scenario, criterion="avoided_co2_kg")["allocation"] == result["allocation"]


def test_relaxing_capacity_recovers_independent_choices(scenario):
    destinations = tuple(replace(d, capacity=2) if d.pathway_id == "repurpose" else d for d in scenario.destinations)
    result = run(replace(scenario, destinations=destinations))
    assert result["allocation"]["assignments"] == {"A": "repurpose", "B": "repurpose"}
    assert result["evaluation"]["economic_objective"] == 18


def test_admission_precedence_and_missing_information():
    rule = PathwaySpec("p", "P", min_soh=0.7, max_safety_class=1, allowed_chemistries=("NMC",))
    unknown = admissibility.assess(BatteryRecord("A"), rule)
    assert unknown.status == "undetermined"
    assert set(unknown.missing_fields) == {"soh", "safety_class", "chemistry"}
    failed = admissibility.assess(BatteryRecord("A", soh=0.6), rule)
    assert failed.status == "ineligible"
    assert failed.missing_fields == ("safety_class", "chemistry")
    assert admissibility.assess(BatteryRecord("A"), PathwaySpec("p", "P")).status == "eligible"


def test_missing_information_not_imputed(scenario):
    partial = replace(scenario, batteries=(replace(scenario.batteries[0], soh=None), scenario.batteries[1]))
    assert run(partial, "admission")["eligibility"][0]["status"] == "undetermined"
    with pytest.raises(ValueError, match="Unresolved eligibility"):
        run(partial)
    with pytest.raises(ValueError, match="complete pack attributes"):
        run(partial, unknown_policy="exclude")


def test_explicit_unknown_exclusion_with_complete_assets(scenario):
    records = list(admissibility.assess_scenario(scenario))
    records[2] = Eligibility("B", "repurpose", "undetermined", ("External qualification is pending",), source="external assessment")
    evidence = eligibility_evidence(scenario, records)
    with pytest.raises(ValueError, match="Unresolved"):
        run(scenario, "allocation", supplied_eligibility=evidence)
    result = run(scenario, "allocation", supplied_eligibility=evidence, unknown_policy="exclude")
    assert result["allocation"]["assignments"] == {"A": "repurpose", "B": "recycle"}


def test_noncompensatory_admission(scenario):
    scenario = replace(scenario, batteries=(replace(scenario.batteries[0], soh=0.5), scenario.batteries[1]),
                       values=tuple(replace(v, economic_value=1e6) if (v.asset_id, v.pathway_id) == ("A", "repurpose") else v for v in scenario.values))
    result = run(scenario)
    assert result["allocation"]["assignments"]["A"] == "recycle"
    assert next(r for r in result["comparisons"] if (r["asset_id"], r["pathway_id"]) == ("A", "repurpose"))["rank"] is None


def test_comparison_ties_are_preserved(scenario):
    scenario = replace(scenario, values=tuple(replace(v, economic_value=5) for v in scenario.values))
    rows = run(scenario, "destination")["comparisons"]
    assert all(row["rank"] == 1 and row["preferred"] for row in rows)


def test_compatible_demand_and_deferral(scenario):
    no_demand = replace(scenario, demand_limits={"repurpose": 0, "recycle": 0})
    result = run(no_demand)
    assert result["allocation"]["assignments"] == {"A": None, "B": None}
    assert result["evaluation"]["economic_objective"] == -4
    assert result["evaluation"]["details"]["deferred_count"] == 2


def test_illustrative_formula_currency_and_provenance(scenario):
    valued = flow.value_synthetic_batteries(scenario, scenario.batteries)
    assert "Model 0 default formulas" in valued.source
    with pytest.raises(ValueError, match="use SGD"):
        flow.value_synthetic_batteries(replace(scenario, currency="EUR"), scenario.batteries)


def test_reasons_describe_joint_choice_and_ineligible_deferral(scenario):
    result = run(scenario)
    assert "higher-valued individual alternative" in result["decision_reasons"][0]["explanation"]
    blocked = replace(scenario, destinations=tuple(replace(d, min_soh=1.0) for d in scenario.destinations))
    assert all("No eligible" in r["explanation"] for r in run(blocked)["decision_reasons"])


def test_infeasible_emissions_floor_has_no_reported_allocation(scenario):
    result = run(replace(scenario, co2_floor_kg=100))
    assert result["status"] == "Infeasible"
    assert result["allocation"] is None and result["evaluation"] is None


def test_supplied_evidence_requires_complete_current_snapshot(scenario):
    with pytest.raises(ValueError, match="requires supplied"):
        run(scenario, "allocation")
    evidence = eligibility_evidence(scenario)
    with pytest.raises(ValueError, match="different scenario"):
        run(replace(scenario, version=2), "allocation", supplied_eligibility=evidence)
    evidence["records"].pop()
    with pytest.raises(ValueError, match="exactly one"):
        run(scenario, "allocation", supplied_eligibility=evidence)


@pytest.mark.parametrize("changes", [{"periods": 2}, {"objective": "avoided_co2_kg"}, {"controllable_actions": ("route",)}, {"deferral_costs": {}}])
def test_unsupported_allocation_contracts_are_rejected(scenario, changes):
    with pytest.raises(ValueError):
        run(replace(scenario, **changes))


def test_missing_values_are_explicit_errors(scenario):
    for mode in ("destination", "integrated"):
        with pytest.raises(ValueError, match="missing assessment"):
            run(replace(scenario, values=()), mode)


def test_model0_default_reduction_and_shared_capacity():
    from level0.instance import default_instance
    from level0.model import solve_milp
    original = default_instance()
    expected = solve_milp(original)
    actual = run(flow.synthetic_scenario())
    assert actual["allocation"]["assignments"] == dict(expected.action.assignments)
    assert actual["evaluation"]["economic_objective"] == pytest.approx(expected.evaluation.economic_objective)
    assert actual["evaluation"]["avoided_co2_kg"] == pytest.approx(expected.evaluation.avoided_co2_kg)
    scenario = replace(flow.synthetic_scenario(), resources=tuple(replace(r, capacity=0) if r.resource_id == "test_bay" else r for r in original.resources))
    assert run(scenario)["evaluation"]["details"]["pathway_counts"]["repurpose"] == 0


def test_existing_custom_coefficients_can_be_used_without_reassessment(scarcity_instance):
    from level0.model import solve_milp
    scenario = flow.scenario_from_model0(scarcity_instance)
    records = tuple(Eligibility(c.asset_id, c.pathway_id, "eligible" if c.admissible else "ineligible",
                                () if c.admissible else ("Excluded in supplied instance",), source="original benchmark coefficients")
                    for c in scarcity_instance.coefficients.values())
    result = run(scenario, "allocation", supplied_eligibility=eligibility_evidence(scenario, records))
    assert result["evaluation"]["economic_objective"] == solve_milp(scarcity_instance).evaluation.economic_objective


def test_scenario_json_roundtrip_and_input_immutability(scenario):
    before = scenario_json(scenario)
    restored = scenario_from_json(before)
    assert fingerprint(restored) == fingerprint(scenario)
    run(scenario)
    assert scenario_json(scenario) == before
    with pytest.raises(TypeError):
        scenario.deferral_costs["A"] = 99


@pytest.mark.parametrize("bad", ['{"schema_version":1,"schema_version":1}', '{"schema_version":1,"scenario":{"values":NaN}}', '{"schema_version":2,"scenario":{}}'])
def test_bad_json_rejected(bad):
    with pytest.raises(ValueError):
        scenario_from_json(bad)


def test_duplicate_and_unknown_records_rejected(scenario):
    with pytest.raises(ValueError, match="duplicate identifiers"):
        replace(scenario, batteries=scenario.batteries + scenario.batteries[:1])
    with pytest.raises(ValueError, match="duplicate pair"):
        replace(scenario, values=scenario.values + scenario.values[:1])
    with pytest.raises(ValueError, match="unknown battery"):
        replace(scenario, values=(OptionValue("missing", "recycle", 1, 1),))
    with pytest.raises(ValueError, match="unknown resource"):
        replace(scenario, values=(replace(scenario.values[0], resource_use={"missing": 1}),))


def test_csv_roundtrip_partial_and_malformed():
    path = ROOT / "data/level0/synthetic_60pack_assets.csv"
    assert len(batteries_from_csv(path.read_bytes())) == 60
    header = b"asset_id,soh,chemistry,safety_class,nameplate_kwh,mass_kg,periods_held\n"
    partial = batteries_from_csv(header + b"X,,NMC,0,60,400,0\n")[0]
    assert partial.soh is None
    for row in (b"X,nan,NMC,0,60,400,0\n", b"X,0.8,NMC,0.5,60,400,0\n", b"X,0.8,NMC,0,60,400\n"):
        with pytest.raises(ValueError):
            batteries_from_csv(header + row)


def test_history_is_append_only_and_reproducible(tmp_path, scenario):
    store = RunStore(tmp_path / "history.sqlite")
    result = run(scenario)
    store.save(result)
    saved = store.load(result["run_id"])
    assert saved == result
    assert store.list_runs()[0]["scenario_id"] == scenario.scenario_id
    with pytest.raises(sqlite3.IntegrityError):
        store.save(result)
    saved["scenario"]["version"] += 1
    with pytest.raises(ValueError, match="fingerprint"):
        store.save(saved)
    replay = run(scenario_from_json(json.dumps({"schema_version": 1, "scenario": result["scenario"]})))
    assert replay["allocation"] == result["allocation"]


def test_saved_comparison_identifies_changed_basis(scenario):
    first = run(scenario)
    second = run(replace(scenario, version=2, demand_limits={"repurpose": 0}))
    comparison = compare_runs(first, second)
    assert set(comparison["changed_scenario_fields"]) == {"version", "demand_limits"}
    assert comparison["differences"]["economic_objective"] == -8
    currency_change = run(replace(scenario, currency="EUR"))
    assert not compare_runs(first, currency_change)["differences"]


def test_planner_independent_integrated_stale_and_infeasible():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(ROOT / "planner/app.py")).run(timeout=30)
    assert not app.exception
    app.selectbox(key="example").set_value("Two-pack capacity example").run()
    app.radio(key="page").set_value("Decision workspace").run()
    app.button(key="run").click().run(timeout=30)
    assert not app.exception
    assert app.metric[0].value == "17.00"
    app.radio(key="page").set_value("Decision workspace").run()
    app.radio(key="mode").set_value("Battery admissibility").run()
    app.button(key="run").click().run()
    assert not app.exception and not app.metric
    app.radio(key="page").set_value("Decision workspace").run()
    app.radio(key="mode").set_value("Allocation planning").run()
    app.button(key="run").click().run(timeout=30)
    assert not app.exception and app.metric[0].value == "17.00"
    app.radio(key="page").set_value("Configuration").run()
    next(c for c in app.checkbox if c.label == "Require minimum avoided emissions").check().run()
    next(n for n in app.number_input if n.label == "Avoided emissions floor (kg CO2e)").set_value(100.0).run()
    app.button(key="apply").click().run()
    app.radio(key="page").set_value("Decision workspace").run()
    app.radio(key="mode").set_value("Integrated decision").run()
    app.button(key="run").click().run(timeout=30)
    assert not app.exception
    assert any("Infeasible" in e.value for e in app.error)
