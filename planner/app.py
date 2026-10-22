"""Start with: python -m streamlit run planner/app.py"""

from dataclasses import replace
import hashlib
import html
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from dss.application import compare_runs, eligibility_evidence, implementation_record, run
from dss.flow import synthetic_scenario, value_synthetic_batteries
from dss.serialization import batteries_from_csv, fingerprint, load_json, plain, scenario_from_json, scenario_json
from dss.storage import RunStore

STORE_PATH = ROOT / "results" / "dss" / "runs.sqlite"
SYNTHETIC_CLOUD = globals().get("SYNTHETIC_CLOUD", False)
MODES = {"Battery admissibility": "admission", "Destination determination": "destination",
         "Flow allocation — Model 0": "allocation", "Integrated decision": "integrated"}

st.set_page_config(page_title="Battery disposition DSS", page_icon="🔋", layout="wide")
st.markdown("""<style>
.block-container {max-width:1450px; padding-top:3rem}
h1,h2,h3 {color:#123958}
.dss-table {border-collapse:collapse; width:100%; font-size:.88rem; margin:1rem 0}
.dss-table th {background:#eaf3f8; color:#123958; text-align:left}
.dss-table td,.dss-table th {padding:.55rem .7rem; border-bottom:1px solid #dbe4ec; vertical-align:top}
.dss-table tr:nth-child(even) {background:#f7fafb}
.dss-scroll {overflow:auto; max-height:460px}
</style>""", unsafe_allow_html=True)


def table(rows):
    """Escaped HTML keeps tables usable without Arrow-based dataframe rendering."""
    rows = list(rows)
    if not rows:
        st.caption("No records for this view.")
        return
    keys = list(rows[0])
    def cell(value):
        if value is None:
            return "—"
        if isinstance(value, list):
            value = "; ".join(str(v) for v in value)
        if isinstance(value, float):
            value = f"{value:,.4f}".rstrip("0").rstrip(".")
        return html.escape(str(value))
    header = "".join(f"<th>{cell(k.replace('_', ' '))}</th>" for k in keys)
    body = "".join("<tr>" + "".join(f"<td>{cell(row.get(k))}</td>" for k in keys) + "</tr>" for row in rows[:300])
    st.markdown(f'<div class="dss-scroll"><table class="dss-table"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>', unsafe_allow_html=True)
    if len(rows) > 300:
        st.caption(f"Showing 300 of {len(rows)} rows; the run download contains every record.")


def configure():
    with st.sidebar:
        st.header("Planning workspace")
        example = st.selectbox("Starting scenario", ["Synthetic 60-pack fleet", "Two-pack capacity example"], key="example")
        uploaded = None if SYNTHETIC_CLOUD else st.file_uploader("Load a complete scenario JSON", type="json")
        base = (scenario_from_json(uploaded.getvalue().decode("utf-8-sig")) if uploaded else
                synthetic_scenario() if example == "Synthetic 60-pack fleet" else
                scenario_from_json((ROOT / "configs/dss/scarcity.json").read_text(encoding="utf-8")))
        base_key = fingerprint(base)[:10]
        if not SYNTHETIC_CLOUD:
            with st.expander("Edit complete scenario / assessments"):
                if st.checkbox("Use edited scenario JSON", key="edit_json"):
                    text = st.text_area("Scenario definition", scenario_json(base), height=350, key=f"json_{base_key}")
                    base = scenario_from_json(text)
                    base_key = fingerprint(base)[:10]
        sid = st.text_input("Scenario name", base.scenario_id, key=f"name_{base_key}")
        revision = st.number_input("Scenario version", min_value=1, value=base.version, key=f"version_{base_key}")
        actor = st.text_input("Decision maker", base.decision_maker, key=f"actor_{base_key}")
        if not SYNTHETIC_CLOUD:
            with st.expander("Import or enter battery records"):
                csv_upload = st.file_uploader("Battery CSV", type="csv")
                manual = st.text_area("Or paste CSV with the seven existing dataset columns", key="manual_csv")
                if csv_upload and manual.strip():
                    raise ValueError("Use either a CSV upload or pasted records, not both")
                content = csv_upload.getvalue() if csv_upload else manual.encode() if manual.strip() else None
                if content is not None:
                    batteries = batteries_from_csv(content)
                    base = replace(base, batteries=batteries, values=(), deferral_costs={},
                                   source=base.source + "; imported battery CSV sha256=" + hashlib.sha256(content).hexdigest())
                    if st.checkbox("Apply illustrative Model 0 valuations to these packs", key="apply_formulas"):
                        base = value_synthetic_batteries(base, batteries)
                    else:
                        st.caption("Admission can use partial records. Comparison/allocation need explicit assessments; use a complete scenario JSON or opt into the illustrative formulas.")
        mode = MODES[st.radio("Decision question", list(MODES), index=3, key="mode")]
        criterion = st.selectbox("Destination comparison criterion", ["economic_value", "avoided_co2_kg"], key="criterion")
        st.caption("Allocation maximises economic value. The comparison criterion does not change its objective.")
        destinations = []
        demand = {}
        with st.expander("Entry requirements, capacity and demand"):
            for d in base.destinations:
                key = f"{base_key}_{d.pathway_id}"
                st.markdown(f"**{d.name}**")
                has_soh = st.checkbox("Minimum SOH applies", d.min_soh is not None, key=f"soh_on_{key}")
                soh = st.number_input("Minimum SOH", min_value=0.0, max_value=1.0, value=d.min_soh or 0.0, step=0.01, key=f"soh_{key}", disabled=not has_soh)
                has_safety = st.checkbox("Safety-class ceiling applies", d.max_safety_class is not None, key=f"safe_on_{key}")
                safety = st.number_input("Maximum safety class", min_value=0, value=d.max_safety_class or 0, key=f"safe_{key}", disabled=not has_safety)
                chem = st.text_input("Allowed chemistries (comma-separated; blank means no rule)", ",".join(d.allowed_chemistries or ()), key=f"chem_{key}")
                bounded = st.checkbox("Limit destination capacity", d.capacity is not None, key=f"cap_on_{key}")
                capacity = st.number_input("Destination capacity", min_value=0.0, value=float(d.capacity or 0), key=f"cap_{key}", disabled=not bounded)
                limit_demand = st.checkbox("Limit compatible demand (packs)", d.pathway_id in base.demand_limits, key=f"dem_on_{key}")
                demand_value = st.number_input("Compatible demand", min_value=0.0, value=float(base.demand_limits.get(d.pathway_id, len(base.batteries))), key=f"dem_{key}", disabled=not limit_demand)
                if limit_demand:
                    demand[d.pathway_id] = demand_value
                destinations.append(replace(d, min_soh=soh if has_soh else None, max_safety_class=safety if has_safety else None,
                                            allowed_chemistries=tuple(c.strip() for c in chem.split(",") if c.strip()) or None,
                                            capacity=capacity if bounded else None))
        resources = []
        with st.expander("Shared resources and emissions constraint"):
            for resource in base.resources:
                capacity = st.number_input(f"{resource.name} ({resource.unit})", min_value=0.0,
                                           value=float(resource.capacity), key=f"res_{base_key}_{resource.resource_id}")
                resources.append(replace(resource, capacity=capacity))
            floor_on = st.checkbox("Require minimum avoided emissions", base.co2_floor_kg is not None, key=f"floor_on_{base_key}")
            floor = st.number_input("Avoided emissions floor (kg CO2e)", min_value=0.0, value=float(base.co2_floor_kg or 0), key=f"floor_{base_key}", disabled=not floor_on)
        scenario = replace(base, scenario_id=sid, version=int(revision), decision_maker=actor,
                           destinations=tuple(destinations), resources=tuple(resources), demand_limits=demand,
                           co2_floor_kg=floor if floor_on else None)
        unknown = "exclude" if st.checkbox("Explicitly exclude undetermined options from allocation", key="exclude_unknown") else "reject"
        evidence = None
        if mode == "allocation":
            evidence_file = None if SYNTHETIC_CLOUD else st.file_uploader("Supplied eligibility JSON", type="json", key="eligibility_upload")
            if st.button("Assess current rules and prepare eligibility", key="prepare"):
                st.session_state["prepared_evidence"] = eligibility_evidence(scenario)
            prepared = st.session_state.get("prepared_evidence")
            if evidence_file:
                evidence = load_json(evidence_file.getvalue().decode("utf-8-sig"))
            elif prepared and prepared["scenario_fingerprint"] == fingerprint(scenario):
                evidence = prepared
            st.caption("Allocation uses supplied evidence. Preparing it above is a separate admission call.")
        submitted = st.button("Run selected capability", type="primary", key="run")
        st.download_button("Download current scenario", scenario_json(scenario), "scenario.json", "application/json")
    return scenario, mode, criterion, unknown, evidence, submitted


def show_result(result):
    st.caption(f"Run {result['run_id'][:8]} · Scenario version {result['scenario']['version']} · Status: {result['status']}")
    report = result["evaluation"]
    if report:
        columns = st.columns(3)
        columns[0].metric(f"Economic objective ({result['scenario']['currency']})", f"{report['economic_objective']:,.2f}")
        columns[1].metric("Assessed avoided emissions (kg CO2e)", f"{report['avoided_co2_kg']:,.2f}")
        columns[2].metric("Deferred packs", str(report["details"]["deferred_count"]))
        st.caption("Certified Model 0 optimum; allocation independently checked for feasibility.")
    elif result["solver"]:
        st.error(f"No certified feasible allocation. Solver status: {result['status']}")
    tabs = st.tabs(["Admission", "Destination comparison", "Allocation & resources", "Assumptions & traceability"])
    with tabs[0]:
        table(result["eligibility"])
        evidence = {"schema_version": 1, "scenario_fingerprint": result["scenario_fingerprint"], "records": result["eligibility"]}
        st.download_button("Download eligibility evidence", json.dumps(evidence, indent=2), "eligibility.json", "application/json")
    with tabs[1]:
        st.caption("Preference among currently eligible destinations. Ties are retained; shared constraints and deferral enter the allocation model.")
        st.caption(f"Economic values: {result['scenario']['currency']} per pair assessment; avoided emissions: kg CO2e.")
        table(result["comparisons"])
    with tabs[2]:
        if result["allocation"]:
            table([{"destination": d["pathway_id"], "assigned_packs": report["details"]["pathway_counts"][d["pathway_id"]],
                    "capacity_use": report["pathway_use"][d["pathway_id"]], "capacity_limit": d["capacity"],
                    "compatible_demand_packs": result["scenario"]["demand_limits"].get(d["pathway_id"])}
                   for d in result["scenario"]["destinations"]])
            limits = {r["resource_id"]: r for r in result["scenario"]["resources"]}
            table([{"resource": k, "use": v, "capacity": limits[k]["capacity"], "unit": limits[k]["unit"]} for k, v in report["resource_use"].items()])
            table(result["decision_reasons"])
            st.caption("Explanations describe the joint solution; a tight constraint alone does not establish the cause of an individual assignment.")
            st.caption("Assignment is an initial disposition decision. Delivered service, waiting duration, material recovery and credited supply are not calculated by Model 0.")
        else:
            st.info("This run has no allocation result.")
    with tabs[3]:
        st.write(result["scenario"]["source"])
        for assumption in result["scenario"]["assumptions"]:
            st.write("• " + assumption)
        st.json({"scenario_fingerprint": result["scenario_fingerprint"], "implementation": result["implementation"],
                 "eligibility_origin": result["eligibility_origin"], "unknown_policy": result["unknown_policy"], "solver": result["solver"]})
    st.download_button("Download complete run", json.dumps(result, indent=2, allow_nan=False), "dss_run.json", "application/json")
    if not SYNTHETIC_CLOUD and st.button("Save run to local history", key="save"):
        try:
            RunStore(STORE_PATH).save(result)
            st.success("Saved with its full input snapshot and provenance.")
        except sqlite3.IntegrityError:
            st.info("This run is already saved.")


st.title("EV battery disposition DSS")
st.write("Assess admissibility, compare destinations, and allocate batteries—independently or together.")
st.caption("Prototype development and focused PhD research share this foundation. Model 0 is the current flow allocation model.")
if SYNTHETIC_CLOUD:
    st.info("Synthetic examples · Download scenarios and results to retain them. Cloud runs stay in your current session; permanent server history is disabled.")
try:
    scenario, mode, criterion, unknown, evidence, submitted = configure()
except (ValueError, TypeError, KeyError, UnicodeDecodeError) as error:
    st.error(f"Input needs attention: {error}")
    st.stop()

request_id = fingerprint({"scenario": scenario, "mode": mode, "criterion": criterion, "unknown": unknown,
                          "evidence": evidence, "core_source": implementation_record()["core_source_sha256"]})
st.caption(f"{scenario.scenario_id} · {len(scenario.batteries)} packs · {len(scenario.destinations)} destinations · {scenario.horizon}")
if submitted:
    st.session_state.pop("current_run", None)
    try:
        with st.spinner("Evaluating the selected decision…"):
            result = run(scenario, mode, supplied_eligibility=evidence, criterion=criterion, unknown_policy=unknown)
        st.session_state["current_run"] = (request_id, result)
    except (ValueError, RuntimeError) as error:
        st.error(str(error))
current = st.session_state.get("current_run")
if current and current[0] == request_id:
    show_result(current[1])
elif current:
    st.warning("Inputs have changed or model code was updated. Run the selected capability to refresh the results.")
else:
    st.info("Configure a scenario and run any capability. The two-pack example illustrates why individual preferences and a joint allocation can differ.")

if not SYNTHETIC_CLOUD:
    with st.expander("Saved runs & reassessment"):
        st.caption("Update a scenario version, rerun, and compare snapshots. Reassessment timing is not optimised.")
        if STORE_PATH.exists():
            store = RunStore(STORE_PATH)
            history = store.list_runs()
            table(history)
            if len(history) >= 2:
                labels = {r["run_id"]: f"{r['scenario_id']} v{r['version']} · {r['mode']} · {r['run_id'][:8]}" for r in history}
                left = st.selectbox("Reference run", list(labels), format_func=labels.get)
                right = st.selectbox("Comparison run", list(labels), index=1, format_func=labels.get)
                st.json(compare_runs(store.load(left), store.load(right)))
        else:
            st.caption("No saved runs yet. History stays locally in results/dss/runs.sqlite.")
