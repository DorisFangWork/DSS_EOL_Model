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
         "Allocation planning": "allocation", "Integrated decision": "integrated"}
PAGES = ["Dashboard", "Decision workspace", "Configuration", "Results & comparison", "Model & assumptions", "Overview"]

st.set_page_config(page_title="Battery disposition DSS", page_icon="🔋", layout="wide")
st.markdown('<style>' + (Path(__file__).with_name("styles.css")).read_text(encoding="utf-8") + '</style>', unsafe_allow_html=True)


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
    body = "".join("<tr>" + "".join(f'<td class="{"numeric" if isinstance(row.get(k), (int, float)) and not isinstance(row.get(k), bool) else ""}">{cell(row.get(k))}</td>' for k in keys) + "</tr>" for row in rows[:300])
    st.markdown(f'<div class="dss-scroll"><table class="dss-table"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>', unsafe_allow_html=True)
    if len(rows) > 300:
        st.caption(f"Showing 300 of {len(rows)} rows; the run download contains every record.")


def reset_configuration():
    st.session_state["config_generation"] = st.session_state.get("config_generation", 0) + 1


def configuration_changes(before, after, path=""):
    """Summarise settings and keep imported record collections compact."""
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        return [row for key in dict.fromkeys([*before, *after])
                for row in configuration_changes(before.get(key), after.get(key),
                                                 f"{path} / {key}" if path else key)]
    if isinstance(before, list) and isinstance(after, list):
        if path in ("destinations", "resources") and len(before) == len(after):
            return [row for old, new in zip(before, after)
                    for row in configuration_changes(old, new, new.get("name", path))]
        before, after = f"{len(before)} records", f"{len(after)} records (updated)"
    return [{"Setting": path.replace("_", " "), "Applied": before, "Draft": after}]


def configure(scenario):
    generation = st.session_state.get("config_generation", 0)
    st.subheader("Set the rules and limits for this scenario")
    st.caption("Edit a draft, then apply it to the shared scenario. Leaving this page discards unapplied edits.")
    with st.container(border=True):
        st.subheader("Scenario")
        uploaded = None if SYNTHETIC_CLOUD else st.file_uploader("Load a complete scenario JSON", type="json", key=f"config_upload_{generation}")
        base = (scenario_from_json(uploaded.getvalue().decode("utf-8-sig")) if uploaded else
                scenario)
        base_key = f"{generation}_{fingerprint(base)[:10]}"
        if not SYNTHETIC_CLOUD:
            with st.expander("Edit complete scenario / assessments"):
                if st.checkbox("Use edited scenario JSON", key=f"edit_json_{generation}"):
                    text = st.text_area("Scenario definition", scenario_json(base), height=350, key=f"json_{base_key}")
                    base = scenario_from_json(text)
                    base_key = f"{generation}_{fingerprint(base)[:10]}"
        details, version = st.columns([3, 1])
        sid = details.text_input("Scenario name", base.scenario_id, key=f"name_{base_key}")
        revision = version.number_input("Scenario version", min_value=1, value=base.version, key=f"version_{base_key}")
        actor = st.text_input("Decision maker", base.decision_maker, key=f"actor_{base_key}")
        if not SYNTHETIC_CLOUD:
            with st.expander("Import or enter battery records"):
                csv_upload = st.file_uploader("Battery CSV", type="csv", key=f"config_csv_{generation}")
                manual = st.text_area("Or paste CSV with the seven existing dataset columns", key=f"manual_csv_{generation}")
                if csv_upload and manual.strip():
                    raise ValueError("Use either a CSV upload or pasted records, not both")
                content = csv_upload.getvalue() if csv_upload else manual.encode() if manual.strip() else None
                if content is not None:
                    batteries = batteries_from_csv(content)
                    base = replace(base, batteries=batteries, values=(), deferral_costs={},
                                   source=base.source + "; imported battery CSV sha256=" + hashlib.sha256(content).hexdigest())
                    if st.checkbox("Apply illustrative Model 0 valuations to these packs", key=f"apply_formulas_{generation}"):
                        base = value_synthetic_batteries(base, batteries)
                    else:
                        st.caption("Admission can use partial records. Comparison/allocation need explicit assessments; use a complete scenario JSON or opt into the illustrative formulas.")
    destinations = []
    demand = {}
    st.subheader("Destinations")
    with st.container():
        for d in base.destinations:
            with st.container(border=True):
                key = f"{base_key}_{d.pathway_id}"
                st.subheader(d.name)
                entry, limits = st.columns(2)
                entry.caption("ENTRY REQUIREMENTS")
                limits.caption("CAPACITY & DEMAND")
                has_soh = entry.checkbox("Minimum SOH applies", d.min_soh is not None, key=f"soh_on_{key}")
                soh = entry.number_input("Minimum SOH (0–1)", help="0.70 means 70% state of health.", min_value=0.0, max_value=1.0, value=d.min_soh or 0.0, step=0.01, key=f"soh_{key}", disabled=not has_soh)
                has_safety = entry.checkbox("Safety-class ceiling applies", d.max_safety_class is not None, key=f"safe_on_{key}")
                safety = entry.number_input("Maximum safety class", help="Battery safety-class number must be at or below this ceiling. Class meanings follow the scenario dataset.", min_value=0, value=d.max_safety_class or 0, key=f"safe_{key}", disabled=not has_safety)
                chem = entry.text_input("Allowed chemistries (comma-separated; blank means no rule)", ",".join(d.allowed_chemistries or ()), key=f"chem_{key}")
                bounded = limits.checkbox("Limit destination capacity", d.capacity is not None, key=f"cap_on_{key}")
                capacity = limits.number_input("Destination capacity (assessment units)", help="Limits total assessed pathway capacity use. If each pack uses one unit, this is a pack limit.", min_value=0.0, value=float(d.capacity or 0), key=f"cap_{key}", disabled=not bounded)
                limit_demand = limits.checkbox("Limit compatible demand (packs)", d.pathway_id in base.demand_limits, key=f"dem_on_{key}")
                demand_value = limits.number_input("Compatible demand (packs)", help="Maximum number of packs assigned to this destination.", min_value=0.0, value=float(base.demand_limits.get(d.pathway_id, len(base.batteries))), key=f"dem_{key}", disabled=not limit_demand)
                if limit_demand:
                    demand[d.pathway_id] = demand_value
                destinations.append(replace(d, min_soh=soh if has_soh else None, max_safety_class=safety if has_safety else None,
                                            allowed_chemistries=tuple(c.strip() for c in chem.split(",") if c.strip()) or None,
                                            capacity=capacity if bounded else None))
    resources = []
    st.subheader("Shared constraints")
    with st.container(border=True):
        for resource in base.resources:
            capacity = st.number_input(f"{resource.name} ({resource.unit})", min_value=0.0,
                                       value=float(resource.capacity), key=f"res_{base_key}_{resource.resource_id}")
            resources.append(replace(resource, capacity=capacity))
        floor_on = st.checkbox("Require minimum avoided emissions", base.co2_floor_kg is not None, key=f"floor_on_{base_key}")
        floor = st.number_input("Avoided emissions floor (kg CO2e)", min_value=0.0, value=float(base.co2_floor_kg or 0), key=f"floor_{base_key}", disabled=not floor_on)
    candidate = replace(base, scenario_id=sid, version=int(revision), decision_maker=actor,
                       destinations=tuple(destinations), resources=tuple(resources), demand_limits=demand,
                       co2_floor_kg=floor if floor_on else None)
    st.subheader("Review & apply")
    with st.container(border=True):
        changes = configuration_changes(plain(scenario), plain(candidate))
        if changes:
            st.caption("Unapplied changes. Existing results still refer to the applied scenario.")
            table(changes)
        else:
            st.caption("All settings match the applied scenario.")
        apply, discard = st.columns(2)
        if apply.button("Apply configuration", type="primary", key="apply", disabled=not changes):
            st.session_state["scenario"] = candidate
            reset_configuration()
            st.session_state["notice"] = "Configuration applied. Run a capability to assess this scenario."
            st.rerun()
        discard.button("Discard changes", on_click=reset_configuration, disabled=not changes)
    with st.expander("Battery inventory"):
        table(plain(candidate.batteries))


def show_result(result):
    title, export = st.columns([3, 1])
    title.subheader(mode_label(result["mode"]))
    export.download_button("Download complete run", json.dumps(result, indent=2, allow_nan=False), "dss_run.json", "application/json", width="stretch")
    st.markdown(f'<span class="result-status">{html.escape(result["status"].title())}</span>', unsafe_allow_html=True)
    st.caption(f"Run {result['run_id'][:8]} · Scenario version {result['scenario']['version']} · Status: {result['status']}")
    report = result["evaluation"]
    if report:
        counts = report["details"]["pathway_counts"]
        st.markdown('<div class="decision-headline">' + html.escape(" · ".join(
            [f"{count} {name.replace('_', ' ')}" for name, count in counts.items()] +
            [f"{report['details']['deferred_count']} deferred"])) + '</div>', unsafe_allow_html=True)
        columns = st.columns(3)
        columns[0].metric(f"Economic objective ({result['scenario']['currency']})", f"{report['economic_objective']:,.2f}")
        columns[1].metric("Assessed avoided emissions (kg CO2e)", f"{report['avoided_co2_kg']:,.2f}")
        columns[2].metric("Deferred packs", str(report["details"]["deferred_count"]))
        st.caption("Optimal allocation; independently checked for feasibility. See Model & assumptions for engine details.")
        allocation_chart(result)
    elif result["solver"]:
        st.error(f"No certified feasible allocation. Solver status: {result['status']}")
    else:
        st.success("Assessment complete. Review the battery–destination evidence below.")
        for column, status in zip(st.columns(3), ("eligible", "ineligible", "undetermined")):
            column.metric(status.title() + " options", sum(r["status"] == status for r in result["eligibility"]))
        st.caption("Counts refer to battery–destination pairs, not unique batteries.")
    selected_asset = st.selectbox("Inspect a battery", ["All batteries"] + [b["asset_id"] for b in result["scenario"]["batteries"]], key=f"inspect_{result['run_id']}")
    def filtered(rows):
        return rows if selected_asset == "All batteries" else [r for r in rows if r.get("asset_id") == selected_asset]
    labels = (["Allocation details", "Admissibility", "Destination comparison", "Traceability"] if result["solver"] else
              ["Destination comparison", "Admissibility", "Allocation details", "Traceability"] if result["mode"] == "destination" else
              ["Admissibility", "Destination comparison", "Allocation details", "Traceability"])
    tabs = dict(zip(labels, st.tabs(labels)))
    with tabs["Admissibility"]:
        table(filtered(result["eligibility"]))
        evidence = {"schema_version": 1, "scenario_fingerprint": result["scenario_fingerprint"], "records": result["eligibility"]}
        st.download_button("Download eligibility evidence", json.dumps(evidence, indent=2), "eligibility.json", "application/json")
    with tabs["Destination comparison"]:
        st.caption("Preference among currently eligible destinations. Ties are retained; shared constraints and deferral enter the allocation model.")
        st.caption(f"Economic values: {result['scenario']['currency']} per pair assessment; avoided emissions: kg CO2e.")
        table(filtered(result["comparisons"]))
    with tabs["Allocation details"]:
        if result["allocation"]:
            table([{"destination": d["pathway_id"], "assigned_packs": report["details"]["pathway_counts"][d["pathway_id"]],
                    "capacity_use": report["pathway_use"][d["pathway_id"]], "capacity_limit": d["capacity"],
                    "compatible_demand_packs": result["scenario"]["demand_limits"].get(d["pathway_id"])}
                   for d in result["scenario"]["destinations"]])
            limits = {r["resource_id"]: r for r in result["scenario"]["resources"]}
            table([{"resource": k, "use": v, "capacity": limits[k]["capacity"], "unit": limits[k]["unit"]} for k, v in report["resource_use"].items()])
            table(filtered(result["decision_reasons"]))
            st.caption("Explanations describe the joint solution; a tight constraint alone does not establish the cause of an individual assignment.")
            st.caption("Assignment is an initial disposition decision. Delivered service, waiting duration, material recovery and credited supply are not calculated by Model 0.")
        else:
            st.info("This run has no allocation result.")
    with tabs["Traceability"]:
        st.write(result["scenario"]["source"])
        for assumption in result["scenario"]["assumptions"]:
            st.write("• " + assumption)
        st.json({"scenario_fingerprint": result["scenario_fingerprint"], "implementation": result["implementation"],
                 "eligibility_origin": result["eligibility_origin"], "unknown_policy": result["unknown_policy"], "solver": result["solver"]})
    if not SYNTHETIC_CLOUD and st.button("Save run to local history", key="save"):
        try:
            RunStore(STORE_PATH).save(result)
            st.success("Saved with its full input snapshot and provenance.")
        except sqlite3.IntegrityError:
            st.info("This run is already saved.")


def go(page, mode=None):
    st.session_state["next_page"] = page
    if mode:
        st.session_state["mode"] = mode


def new_analysis():
    st.session_state.pop("mode", None)
    go("Decision workspace")


def current_basis(result, scenario):
    return (result["scenario_fingerprint"] == fingerprint(scenario)
            and result["implementation"]["core_source_sha256"] == implementation_record()["core_source_sha256"])


def review_run(run_id):
    st.session_state["selected_run"] = run_id
    go("Results & comparison")


def allocation_chart(result):
    report = result.get("evaluation")
    if not report:
        return
    st.subheader("Planned disposition")
    counts = dict(report["details"]["pathway_counts"])
    counts["Deferred"] = report["details"]["deferred_count"]
    total = len(result["scenario"]["batteries"])
    colours = ["#588157", "#a3b18a", "#e9e2d3"]
    rows = []
    for i, (name, count) in enumerate(counts.items()):
        rows.append(f'<div class="allocation-row"><span>{html.escape(name.replace("_", " ").title())}</span>'
                    f'<div class="allocation-track"><div style="width:{100 * count / total:.2f}%;background:{colours[i % 3]}"></div></div>'
                    f'<strong>{count} packs</strong></div>')
    st.markdown('<div class="allocation-chart">' + ''.join(rows) + '</div>', unsafe_allow_html=True)


def capability_cards(compact=False):
    descriptions = [
        ("Battery admissibility", "Eligibility & evidence", "Check which destinations each battery can enter and identify unmet requirements."),
        ("Destination determination", "Options & preferences", "Compare eligible destinations using economic value or assessed avoided emissions."),
        ("Allocation planning", "Fleet & constraints", "Distribute batteries across destinations within demand and shared capacity limits."),
    ]
    for column, (name, label, description) in zip(st.columns(3), descriptions):
        with column, st.container(border=True, key=f"capability_{MODES[name]}"):
            symbol = {"admission": "✓", "destination": "⇄", "allocation": "▥"}[MODES[name]]
            st.markdown(f'<div class="capability-copy{" compact" if compact else ""}">'
                        f'<div class="eyebrow"><span class="capability-icon" aria-hidden="true">{symbol}</span>{html.escape(label)}</div>'
                        f'<h3>{html.escape(name)}</h3>' + ("" if compact else f'<p>{html.escape(description)}</p>') + '</div>', unsafe_allow_html=True)
            action = {"admission": "Assess eligibility", "destination": "Compare options", "allocation": "Plan allocation"}[MODES[name]]
            st.button(action, key=f"open_{MODES[name]}", on_click=go, args=("Decision workspace", name), width="stretch")


def overview(scenario):
    st.markdown('<section class="about-intro"><div class="eyebrow">EV BATTERY DISPOSITION · DECISION SUPPORT</div>'
                '<h2>One planning context. Three connected capabilities.</h2>'
                '<p>Turn battery information and operational constraints into traceable disposition plans.</p>'
                '<div class="product-paths"><span>BATTERY INFORMATION</span><b>↔</b><span>DECISION CAPABILITIES</span><b>↔</b><span>PLANNING CONTEXT</span></div></section>', unsafe_allow_html=True)
    left, right = st.columns([1, 1])
    left.button("Open planning dashboard", on_click=go, args=("Dashboard",), width="stretch")
    right.button("Explore a decision", key="workflow_explore", on_click=go, args=("Decision workspace",), width="stretch")
    st.subheader("Make the trade-offs visible")
    st.write("A battery can suit more than one destination. Limited capacity, compatible demand and competing priorities determine which options make sense for the fleet. Disposition DSS brings these decisions into one shared planning workspace.")
    st.caption("For OEM disposition planners and teams evaluating second-life and recycling options.")
    capability_cards()
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader("Bring a decision. Leave with a plan.")
        st.write("Define destination requirements and operational limits. Assess available options, allocate batteries and compare alternative scenarios.")
        st.write("Review battery-level assignments, eligibility explanations and the economic and emissions assessments behind the result. Export the complete decision record for discussion.")
    with right, st.container(border=True):
        st.subheader("Start with your planning question")
        st.write("Which batteries meet an entry requirement? Where does scarce repurposing capacity add the most assessed value? How does the plan change when capacity or demand changes?")
        st.write("Use each capability separately or together. Shared inputs and traceable evidence connect the decisions.")
    with st.expander("Evaluate the prototype for your organisation"):
        st.write("A useful pilot starts with one decision owner, a defined battery population and agreed destination rules. Validate assessment values and capacity assumptions, compare plans against current practice, and review recommendations with operational specialists.")
        st.info("This private preview uses synthetic data and session-only cloud history. Industry deployment requires validated operational data, durable storage and organisation-specific access controls. Download results before ending a session.")
        st.button("Review model scope", on_click=go, args=("Model & assumptions",))


def dashboard(scenario):
    history = st.session_state["runs"]
    st.markdown('<div class="context-strip">' + ''.join(
        f'<span><strong>{value}</strong> {label}</span>' for value, label in [
            (len(scenario.batteries), "battery packs"), (len(scenario.destinations), "destinations"),
            (len(scenario.resources), "shared resources"), (len(history), "session analyses")]) + '</div>', unsafe_allow_html=True)
    if not history:
        capability_cards(compact=True)
    with st.container(border=True, key="latest_card"):
        st.subheader("Latest analysis")
        if history:
            latest = history[-1]
            summary, action = st.columns([3, 1])
            summary.caption(f"{mode_label(latest['mode'])} · {latest['status']} · {latest['scenario']['scenario_id']} · {latest['run_id'][:8]}")
            action.button("Review results", key="review_latest", on_click=review_run, args=(latest["run_id"],), width="stretch")
            if not current_basis(latest, scenario):
                st.warning("This analysis uses an earlier scenario or model version.")
            else:
                st.caption("Current inputs · Matches the applied scenario and model.")
            if latest.get("evaluation"):
                chart, outcomes = st.columns([1.5, 1])
                with chart:
                    allocation_chart(latest)
                with outcomes:
                    report = latest["evaluation"]
                    st.metric(f"Economic objective ({latest['scenario']['currency']})", f"{report['economic_objective']:,.2f}")
                    st.metric("Assessed avoided emissions (kg CO2e)", f"{report['avoided_co2_kg']:,.2f}")
            elif latest.get("solver"):
                st.warning("No certified feasible plan. Review the analysis before using its results.")
            else:
                table([{"status": status.title(), "battery_destination_options": sum(r["status"] == status for r in latest["eligibility"])}
                       for status in ("eligible", "ineligible", "undetermined")])
        else:
            st.write("Ready to plan your battery dispositions")
            st.caption("Choose any tool above, or assess eligibility and create a fleet plan together.")
            st.button("Start integrated analysis", key="workflow_integrated", on_click=go, args=("Decision workspace", "Integrated decision"))
    if history:
        capability_cards(compact=True)
    with st.expander("Planning context and limits"):
        st.write(scenario.decision_maker)
        st.caption(scenario.horizon)
        table([{"destination": d.name, "capacity": d.capacity, "demand_limit_packs": scenario.demand_limits.get(d.pathway_id)} for d in scenario.destinations])
        st.button("Configure scenario", on_click=go, args=("Configuration",))
    st.subheader("Recent activity")
    history = st.session_state["runs"]
    if history:
        for r in reversed(history[-5:]):
            with st.container(key=f"activity_{r['run_id']}"):
                summary, action = st.columns([4, 1])
                with summary:
                    st.write(f"**{mode_label(r['mode'])}** · {r['status']}")
                    basis = "Current inputs" if current_basis(r, scenario) else "Historical inputs"
                    st.caption(f"{r['scenario']['scenario_id']} · {r['run_id'][:8]} · {basis}")
                action.button("Open run", key=f"review_{r['run_id']}", on_click=review_run, args=(r["run_id"],), width="stretch")
        st.caption("Showing the latest five runs. All session runs remain in Results & comparison.")
    else:
        st.caption("Completed assessments and allocation plans will appear here.")
    with st.expander(f"Battery inventory · {len(scenario.batteries)} packs"):
        query = st.text_input("Find a battery", placeholder="Battery ID or chemistry", key="inventory_search").strip().casefold()
        rows = [b for b in plain(scenario.batteries) if not query or
                query in str(b["asset_id"]).casefold() or query in str(b.get("chemistry", "")).casefold()]
        st.caption(f"{len(rows)} of {len(scenario.batteries)} batteries")
        if rows:
            table(rows)
        else:
            st.info("No batteries match your search. Try another ID or chemistry.")


def mode_label(mode):
    return next((label for label, value in MODES.items() if value == mode), mode)


def workspace(scenario):
    st.subheader("What decision do you need to make?")
    st.caption("Choose a question. These capabilities share the same scenario and can be used independently.")
    selected = st.session_state.get("mode")
    choices = [
        ("Battery admissibility", "Can this battery enter a destination?", "Check eligibility", "✓"),
        ("Destination determination", "Which destination is preferable?", "Compare destinations", "⇄"),
        ("Allocation planning", "How should the fleet be allocated?", "Plan allocation", "▥"),
    ]
    for column, (name, question, action, symbol) in zip(st.columns(3), choices):
        active = selected == name
        with column, st.container(border=True, key=f"question_{'selected' if active else 'option'}_{MODES[name]}"):
            st.markdown(f'<div class="question-copy"><span class="question-label">{symbol} {html.escape(name)}</span>'
                        f'<h3>{html.escape(question)}</h3></div>', unsafe_allow_html=True)
            st.button(f"Selected · {action}" if active else action, key=f"choose_{name}",
                      type="secondary", on_click=go,
                      args=("Decision workspace", name), width="stretch")
    integrated = selected == "Integrated decision"
    with st.container(key="integrated_option"):
        explanation, choose = st.columns([3, 2], vertical_alignment="center")
        explanation.caption("Combine capabilities: assess eligibility and plan the fleet together.")
        choose.button("Selected · Assess and plan together" if integrated else "Assess and plan together",
                      key="choose_Integrated decision", on_click=go,
                      args=("Decision workspace", "Integrated decision"),
                      type="secondary", width="stretch")
    if selected not in MODES:
        st.info("Select a decision question above to see its settings and run the analysis.")
        return
    mode = MODES[selected]
    descriptions = {
        "admission": "Assess destination-specific eligibility. Unknown information is reported explicitly.",
        "destination": "Compare eligible options per battery. Preferences are advisory and do not impose a fleet allocation.",
        "allocation": "Use eligibility evidence to find the economically optimal fleet allocation under shared limits.",
        "integrated": "Assess eligibility and jointly allocate the fleet. Destination rankings explain options without constraining the optimiser.",
    }
    with st.container(border=True, key="decision_card"):
        st.caption("SELECTED ANALYSIS · SETTINGS & ACTION")
        st.subheader(mode_label(mode))
        st.write(descriptions[mode])
        criterion = st.session_state.get("criterion", "economic_value")
        if mode in {"destination", "integrated"}:
            criterion = st.selectbox("Destination comparison criterion", ["economic_value", "avoided_co2_kg"],
                                     format_func=lambda x: {"economic_value": "Economic value", "avoided_co2_kg": "Avoided emissions"}[x],
                                     key="criterion", persist_state="session")
        unknown = "exclude" if st.session_state.get("exclude_unknown", False) else "reject"
        evidence = None
        if mode in {"allocation", "integrated"}:
            st.caption("Allocation maximises economic value. An emissions floor can be set in Configuration; the comparison criterion does not change the allocation objective.")
            unknown = "exclude" if st.checkbox("Explicitly exclude undetermined options from allocation", key="exclude_unknown", persist_state="session") else "reject"
        if mode == "allocation":
            evidence_file = None if SYNTHETIC_CLOUD else st.file_uploader("Supplied eligibility JSON", type="json", key="eligibility_upload")
            if st.button("Assess current rules and prepare eligibility", key="prepare", type="primary" if st.session_state.get("prepared_evidence", {}).get("scenario_fingerprint") != fingerprint(scenario) else "secondary"):
                st.session_state["prepared_evidence"] = eligibility_evidence(scenario)
            if evidence_file:
                st.session_state["prepared_evidence"] = load_json(evidence_file.getvalue().decode("utf-8-sig"))
            prepared = st.session_state.get("prepared_evidence")
            if prepared and prepared.get("scenario_fingerprint") == fingerprint(scenario):
                evidence = prepared
                st.success("Eligibility evidence matches this scenario.")
            else:
                st.warning("Prepare matching eligibility evidence, or run Battery admissibility first. Earlier evidence cannot be reused after scenario changes.")
        actions = {"admission": "Assess battery eligibility", "destination": "Compare destination options",
                   "allocation": "Create allocation plan", "integrated": "Assess and create plan"}
        if mode != "allocation" or evidence is not None:
            st.caption("Ready to run with the applied scenario.")
        if st.button(actions[mode], type="primary", key="run", disabled=mode == "allocation" and evidence is None):
            try:
                with st.spinner("Evaluating the decision…"):
                    result = run(scenario, mode, supplied_eligibility=evidence, criterion=criterion, unknown_policy=unknown)
                st.session_state["runs"].append(result)
                st.session_state["selected_run"] = result["run_id"]
                # Prefer comparable plans over eligibility-only assessments on a new run.
                if result.get("evaluation") and result["evaluation"]["feasible"]:
                    for previous in reversed(st.session_state["runs"][:-1]):
                        if (previous.get("evaluation") and previous["evaluation"]["feasible"]
                                and previous["scenario"]["scenario_id"] == result["scenario"]["scenario_id"]
                                and compare_runs(previous, result)["differences"]):
                            st.session_state["baseline_run"] = previous["run_id"]
                            st.session_state["alternative_run"] = result["run_id"]
                            break
                st.session_state["prepared_evidence"] = {"schema_version": 1, "scenario_fingerprint": result["scenario_fingerprint"], "records": result["eligibility"]}
                go("Results & comparison")
                st.rerun()
            except (ValueError, RuntimeError) as error:
                st.error(str(error))
    with st.expander("Inspect applied inputs"):
        st.caption(f"Scenario fingerprint: {fingerprint(scenario)[:16]}")
        table(plain(scenario.batteries))
    st.button("Change configuration", on_click=go, args=("Configuration",))


def compare_view(history):
    if len(history) < 2:
        st.info("Run a baseline, change and apply a configuration, then run an alternative. Both snapshots will be available here.")
        return
    lookup = {r["run_id"]: r for r in history}
    def label(key):
        r = lookup[key]
        return f"{r['scenario']['scenario_id']} v{r['scenario']['version']} · {mode_label(r['mode'])} · {key[:8]}"
    left, right = st.columns(2)
    first_id = left.selectbox("Baseline run", list(lookup), format_func=label, key="baseline_run", persist_state="session")
    second_id = right.selectbox("Alternative run", list(lookup), index=len(lookup) - 1, format_func=label, key="alternative_run", persist_state="session")
    first, second = lookup[first_id], lookup[second_id]
    if first_id == second_id:
        st.info("Select two different runs to compare.")
        return
    comparison = compare_runs(first, second)
    st.caption("Alternative minus baseline. These are scenario differences, not demonstrated coordination gains or causal effects.")
    diffs = comparison["differences"]
    if diffs:
        a, b = st.columns(2)
        a.metric(f"Economic value ({second['scenario']['currency']})", f"{second['evaluation']['economic_objective']:,.2f}", delta=f"{diffs['economic_objective']:+,.2f}", delta_color="off")
        b.metric("Avoided emissions (kg CO2e)", f"{second['evaluation']['avoided_co2_kg']:,.2f}", delta=f"{diffs['avoided_co2_kg']:+,.2f}", delta_color="off")
        table([{"metric": name, "baseline": first["evaluation"][name], "alternative": second["evaluation"][name], "difference": value} for name, value in diffs.items()])
    else:
        st.warning("Numeric outcome comparison requires two evaluated allocations with matching currency and planning horizon.")
    st.subheader("What changed")
    changed = comparison["changed_scenario_fields"]
    table([{"scenario_field": key, "baseline": json.dumps(first["scenario"].get(key), ensure_ascii=False), "alternative": json.dumps(second["scenario"].get(key), ensure_ascii=False)} for key in changed])
    st.caption("Changed analysis settings: " + (", ".join(comparison["changed_run_fields"]) or "None"))
    if first.get("allocation") and second.get("allocation"):
        a, b = first["allocation"]["assignments"], second["allocation"]["assignments"]
        if set(a) != set(b):
            st.warning("The battery populations differ. Review additions and removals before interpreting aggregate changes.")
        st.subheader("Changed battery assignments")
        table([{"battery": key, "baseline": a.get(key) if key in a else "Not in scenario", "alternative": b.get(key) if key in b else "Not in scenario"} for key in sorted(set(a) | set(b)) if key not in a or key not in b or a[key] != b[key]])
        st.caption("A blank destination means deferred.")
    st.download_button("Download comparison and snapshots", json.dumps({"baseline": first, "alternative": second, "comparison": comparison}, indent=2, allow_nan=False), "dss_comparison.json", "application/json")


def results_page(scenario):
    history = st.session_state["runs"]
    st.caption("Completed analyses retain their input snapshots. Cloud history lasts for this session; download results to keep them.")
    if not history:
        st.info("No analyses yet. Open the Decision workspace to run a capability.")
        st.button("Open decision workspace", key="workflow_workspace", on_click=go, args=("Decision workspace",))
    else:
        result_tab, compare_tab = st.tabs(["Analysis results", "Compare scenarios"])
        with result_tab:
            lookup = {r["run_id"]: r for r in history}
            selected = st.selectbox("Analysis run", list(lookup), format_func=lambda key: f"{lookup[key]['scenario']['scenario_id']} · {mode_label(lookup[key]['mode'])} · {key[:8]}", key="selected_run", persist_state="session")
            result = lookup[selected]
            if not current_basis(result, scenario):
                st.warning("Inputs have changed or model code was updated. This is a historical snapshot, not a recommendation for the active scenario.")
            show_result(result)
        with compare_tab:
            compare_view(history)
    if not SYNTHETIC_CLOUD:
        saved_history()


def saved_history():
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


def assumptions(scenario):
    st.subheader("Understand the model and its limits")
    st.write("The DSS is an industry-oriented product prototype. Validated research can strengthen its modular capabilities.")
    st.write("Allocation engine: Model 0 — deterministic, one-period economic optimisation, with admissibility, demand and shared-resource constraints.")
    st.info("Results are planned initial disposition decisions. Delivered service, subsequent qualification, material recovery and credited supply are outside this model's current calculations.")
    st.subheader("Source scenario notes")
    st.caption("These notes describe the original example. Applied configuration and saved run snapshots define the current planning case.")
    st.write(scenario.source)
    for assumption in scenario.assumptions:
        st.write("• " + assumption)
    st.subheader("Assessment values")
    st.caption(f"Economic values in {scenario.currency}; avoided emissions in kg CO2e. These inputs are distinct from operational capacity and entry requirements.")
    table(plain(scenario.values))
    with st.expander("Implementation and provenance"):
        st.json(implementation_record())


if "next_page" in st.session_state:
    st.session_state["page"] = st.session_state.pop("next_page")
st.session_state.setdefault("runs", [])
st.session_state.setdefault("page", "Dashboard")
with st.sidebar:
    st.markdown('<div class="brand"><span class="brand-mark">D</span><div>DISPOSITION DSS<small>EV BATTERY DECISION SUPPORT</small></div></div>', unsafe_allow_html=True)
    st.caption("WORKSPACE")
    icons = [":material/dashboard:", ":material/hub:", ":material/tune:", ":material/compare_arrows:", ":material/description:", ":material/info:"]
    with st.container(key="navigation"):
        for destination, icon in zip(PAGES, icons):
            st.button("About the DSS" if destination == "Overview" else destination,
                      icon=icon, key=f"nav_{destination}", width="stretch",
                      type="primary" if st.session_state["page"] == destination else "secondary",
                      on_click=go, args=(destination,))
    st.divider()
    st.caption("Synthetic examples · Session-only results · Download snapshots to retain your work" if SYNTHETIC_CLOUD else "Local planning workspace")

# Resolve the active example before rendering its name in the shared banner.
example = st.session_state.get("example", "Synthetic 60-pack fleet")
if st.session_state.get("loaded_example") != example:
    st.session_state["scenario"] = (synthetic_scenario() if example == "Synthetic 60-pack fleet" else scenario_from_json((ROOT / "configs/dss/scarcity.json").read_text(encoding="utf-8")))
    st.session_state["loaded_example"] = example
scenario = st.session_state["scenario"]

scenario_control, heading, action = st.columns([2.4, 1.8, 1.2], vertical_alignment="center")
with scenario_control, st.container(key="scenario_selector"):
    st.selectbox(
        "Scenario", ["Synthetic 60-pack fleet", "Two-pack capacity example"], key="example",
        help=f"Active scenario: {scenario.scenario_id}. Changing the example replaces inputs; "
             "completed runs stay in this session. Edit rules and limits on the Configuration page.",
    )

page = st.session_state["page"]
with heading:
    st.caption(f"Version {scenario.version} · {len(scenario.batteries)} packs")
with action:
    st.button("New analysis", type="secondary", icon=":material/add:", on_click=new_analysis,
              help="Start another analysis using the current scenario.", width="stretch")
st.markdown('<div class="header-rule"></div>', unsafe_allow_html=True)
st.title("About the DSS" if page == "Overview" else page)
if "notice" in st.session_state:
    st.success(st.session_state.pop("notice"))
try:
    {"Overview": overview, "Dashboard": dashboard, "Decision workspace": workspace, "Configuration": configure,
     "Results & comparison": results_page, "Model & assumptions": assumptions}[page](scenario)
except (ValueError, TypeError, KeyError, UnicodeDecodeError) as error:
    st.error(f"Input needs attention: {error}")
