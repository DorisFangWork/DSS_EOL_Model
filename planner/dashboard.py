"""Central Decision-maker view over one scenario or completed run snapshot.

Each perspective is a separate renderer so future permissions can select views.
This module does not execute models or implement access control.
"""

import html
import json
from datetime import datetime, timezone

import streamlit as st

from dss.application import compare_runs
from dss.serialization import plain


def snapshot_summary(scenario, result=None):
    """Derive display facts from one basis; never supplement an incomplete run."""
    basis = result["scenario"] if result else plain(scenario)
    records = result["eligibility"] if result else None
    report = result.get("evaluation") if result else None
    plan = report if report and report["feasible"] and result.get("allocation") else None
    confirmed = {r["asset_id"] for r in records or () if r["status"] == "eligible"}
    missing = [
        {"battery": b["asset_id"], "missing_observations": [field for field in
         ("soh", "chemistry", "safety_class", "nameplate_kwh", "mass_kg") if b.get(field) is None]}
        for b in basis["batteries"]
    ]
    values = {(v["asset_id"], v["pathway_id"]) for v in basis["values"]}
    return {
        "scenario": basis, "result": result, "plan": plan,
        "eligibility_counts": None if records is None else {
            status: sum(r["status"] == status for r in records)
            for status in ("eligible", "ineligible", "undetermined")},
        "confirmed_packs": len(confirmed) if records is not None else None,
        "missing_observations": [row for row in missing if row["missing_observations"]],
        "missing_values": None if records is None else sum(
            r["status"] == "eligible" and (r["asset_id"], r["pathway_id"]) not in values for r in records),
    }


def _counts(items):
    st.markdown('<div class="central-counts">' + ''.join(
        f'<div class="count-{tone}"><strong>{html.escape(str(value))}</strong><span>{html.escape(label)}</span></div>'
        for label, value, tone in items) + '</div>', unsafe_allow_html=True)


def _run_label(result, mode_label):
    return f"{result['scenario']['scenario_id']} v{result['scenario']['version']} · {mode_label(result['mode'])} · {result['run_id'][:8]}"


def planning_section(summary, *, table, allocation_chart, go):
    st.subheader("Disposition planning")
    st.caption("Where should the fleet go, and which limits shape the plan?")
    plan, result, basis = summary["plan"], summary["result"], summary["scenario"]
    if plan:
        allocation_chart(result)
        with st.expander("Capacity and resource use"):
            table([{"destination": d["name"], "assigned_packs": plan["details"]["pathway_counts"][d["pathway_id"]],
                    "capacity_use": plan["pathway_use"][d["pathway_id"]], "capacity_limit": d["capacity"],
                    "demand_limit_packs": basis["demand_limits"].get(d["pathway_id"])} for d in basis["destinations"]])
            table([{"resource": r["name"], "use": plan["resource_use"][r["resource_id"]],
                    "capacity": r["capacity"], "unit": r["unit"]} for r in basis["resources"]])
    elif result and result.get("solver"):
        st.warning(f"No certified feasible plan · {result['status']}")
    else:
        st.info("No allocation in this view. Open allocation planning or assess and plan together.")
    st.button("Plan allocation", key="open_allocation", on_click=go,
              args=("Decision workspace", "Allocation planning"))


def technical_section(summary, *, table, go):
    st.subheader("Technical assessment")
    st.caption("Which options meet the entry rules, and what needs attention?")
    counts, result = summary["eligibility_counts"], summary["result"]
    if counts is None:
        st.info("Eligibility has not been assessed in this view.")
    else:
        _counts([("Eligible options", counts["eligible"], "eligible"),
                 ("Ineligible options", counts["ineligible"], "neutral"),
                 ("Undetermined options", counts["undetermined"],
                  "attention" if counts["undetermined"] else "neutral")])
        st.caption(f"Battery–destination pairs · {summary['confirmed_packs']} of {len(summary['scenario']['batteries'])} packs have at least one confirmed eligible destination.")
        if counts["undetermined"]:
            st.warning(f"{counts['undetermined']} options need more information.")
        if summary["missing_values"]:
            st.warning(f"{summary['missing_values']} eligible options lack value assessments for comparison or allocation.")
        with st.expander("Unmet requirements and missing information"):
            issues = [r for r in result["eligibility"] if r["status"] != "eligible"]
            if issues:
                table([{"battery": r["asset_id"], "destination": r["pathway_id"], "status": r["status"],
                        "reasons": r["reasons"], "missing_fields": r["missing_fields"]} for r in issues])
            else:
                st.caption("All assessed options meet the configured entry rules.")
            if summary["missing_observations"]:
                st.caption("Missing pack observations required by Model 0")
                table(summary["missing_observations"])
    if counts is None and summary["missing_observations"]:
        st.caption(f"{len(summary['missing_observations'])} packs have missing observations required by Model 0.")
    left, right = st.columns(2)
    left.button("Assess eligibility", key="open_admission", on_click=go,
                args=("Decision workspace", "Battery admissibility"), width="stretch")
    right.button("Compare destinations", key="open_destination", on_click=go,
                 args=("Decision workspace", "Destination determination"), width="stretch")


def management_section(summary, history, *, go, mode_label):
    st.subheader("Management overview")
    st.caption("What are the modelled outcomes, and how do alternatives compare?")
    plan, result = summary["plan"], summary["result"]
    if not plan:
        st.info("Economic and emissions outcomes will appear for a certified allocation.")
    else:
        outcomes = st.container(key="dashboard_outcomes")
        alternatives = {r["run_id"]: r for r in history if r["run_id"] != result["run_id"]
                        and r.get("evaluation") and r["evaluation"]["feasible"] and r.get("allocation")}
        differences = {}
        if alternatives:
            options = [None, *alternatives]
            if st.session_state.get("dashboard_baseline") not in options:
                st.session_state["dashboard_baseline"] = None
            baseline_id = st.selectbox("Compare against baseline", options, key="dashboard_baseline",
                                      format_func=lambda key: "No baseline selected" if key is None else _run_label(alternatives[key], mode_label))
            if baseline_id:
                comparison = compare_runs(alternatives[baseline_id], result)
                differences = comparison["differences"]
                if not differences:
                    st.warning("Numeric comparison unavailable: evaluated allocations must have matching currency, horizon and period count.")
                else:
                    st.caption("Deltas = selected analysis minus baseline. These are descriptive scenario differences.")
                    if comparison["changed_scenario_fields"] or comparison["changed_run_fields"]:
                        with st.expander("What differs from the baseline"):
                            st.write({"scenario_fields": comparison["changed_scenario_fields"],
                                      "analysis_fields": comparison["changed_run_fields"]})
        with outcomes:
            economic, emissions = st.columns(2)
            for column, key, label in [(economic, "economic_objective", f"Economic objective ({summary['scenario']['currency']})"),
                                       (emissions, "avoided_co2_kg", "Assessed avoided emissions (kg CO2e)")]:
                delta = f"{differences[key]:+,.2f}" if key in differences else None
                column.metric(label, f"{plan[key]:,.2f}", delta=delta, delta_color="off")
            st.caption(f"{plan['details']['deferred_count']} deferred packs · Economic value includes current-period deferral costs.")
        st.caption("Modelled initial disposition outcomes; delivered service and material recovery are not calculated.")
    st.button("Open results & comparison", key="central_compare", on_click=go, args=("Results & comparison",))


def review_section(summary, *, table, go, review_run, mode_label):
    st.subheader("Review & assurance")
    st.caption("Can the decision basis, checks and assumptions be traced?")
    result, basis = summary["result"], summary["scenario"]
    if result:
        solver = result.get("solver")
        checks = [("Analysis status", result["status"])]
        if solver:
            checks += [("Solver optimality certificate", "Present" if solver.get("exact_certificate") else "Not certified"),
                       ("Independent feasibility", "Verified" if summary["plan"] else "No verified allocation")]
        else:
            checks.append(("Allocation checks", "Not applicable to this assessment"))
        table([{"check": name, "outcome": value} for name, value in checks])
        recorded = datetime.fromisoformat(result["recorded_at_utc"]).astimezone(timezone.utc).strftime("%d %b %Y · %H:%M UTC")
        st.caption(f"{mode_label(result['mode'])} · Run {result['run_id'][:8]} · {recorded}")
        with st.expander("Evidence and provenance"):
            st.write(basis["source"])
            for assumption in basis["assumptions"]:
                st.write("• " + assumption)
            st.json({"scenario_fingerprint": result["scenario_fingerprint"], "implementation": result["implementation"],
                     "eligibility_origin": result["eligibility_origin"], "unknown_policy": result["unknown_policy"]})
        review, download = st.columns(2)
        review.button("Review selected results", key="review_latest", on_click=review_run,
                      args=(result["run_id"],), width="stretch")
        download.download_button("Download analysis", json.dumps(result, indent=2, allow_nan=False),
                                 "dss_run.json", "application/json", key="central_download", width="stretch")
    else:
        st.info("Run an analysis to inspect its evidence, model checks and input snapshot.")
    st.button("Review model scope", key="central_model", on_click=go, args=("Model & assumptions",))
    st.caption("This view supports review. Operational approval is not recorded by the prototype.")


def render_dashboard(scenario, history, *, go, review_run, table, allocation_chart, mode_label, current_basis):
    heading, action = st.columns([3, 1.4], vertical_alignment="center")
    with heading:
        st.subheader("Central Decision-maker")
        st.caption("One view of disposition planning, technical assessment, management and review.")
    action.button("Assess and plan together", key="workflow_integrated", on_click=go,
                  args=("Decision workspace", "Integrated decision"), width="stretch")
    with st.container(border=True, key="dashboard_context"):
        result = None
        if history:
            lookup = {r["run_id"]: r for r in history}
            if st.session_state.get("selected_run") not in lookup:
                st.session_state["selected_run"] = history[-1]["run_id"]
            selected = st.selectbox("Analysis snapshot", list(lookup), key="selected_run", persist_state="session",
                                    format_func=lambda key: _run_label(lookup[key], mode_label))
            result = lookup[selected]
            if current_basis(result, scenario):
                st.caption("Current inputs · All four sections use this selected analysis.")
            else:
                st.warning("Historical snapshot: this analysis uses an earlier scenario or model version. All four sections show its saved inputs and results; the toolbar shows the currently applied scenario.")
        else:
            st.caption("Applied scenario · No completed analysis yet. Choose any capability to begin.")
        summary = snapshot_summary(scenario, result)
        basis = summary["scenario"]
        st.markdown('<div class="context-strip">' + ''.join(
            f'<span><strong>{value}</strong> {label}</span>' for value, label in [
                (len(basis["batteries"]), "battery packs"), (len(basis["destinations"]), "destinations"),
                (len(basis["resources"]), "shared resources"), (len(history), "session analyses")]) + '</div>', unsafe_allow_html=True)
        st.caption(f"Decision owner: {basis['decision_maker']} · {basis['horizon']}")
    planning, technical = st.columns(2, gap="medium")
    with planning, st.container(border=True, key="central_planning", height="stretch"):
        planning_section(summary, table=table, allocation_chart=allocation_chart, go=go)
    with technical, st.container(border=True, key="central_technical", height="stretch"):
        technical_section(summary, table=table, go=go)
    management, review = st.columns(2, gap="medium")
    with management, st.container(border=True, key="central_management", height="stretch"):
        management_section(summary, history, go=go, mode_label=mode_label)
    with review, st.container(border=True, key="central_review", height="stretch"):
        review_section(summary, table=table, go=go, review_run=review_run, mode_label=mode_label)
    with st.expander("Planning context and limits"):
        table([{"destination": d["name"], "capacity": d["capacity"],
                "demand_limit_packs": basis["demand_limits"].get(d["pathway_id"])} for d in basis["destinations"]])
        st.caption("Configure scenario opens the currently applied scenario; saved snapshots stay unchanged.")
        st.button("Configure scenario", on_click=go, args=("Configuration",))
    with st.expander(f"Battery inventory · {len(basis['batteries'])} packs"):
        query = st.text_input("Find a battery", placeholder="Battery ID or chemistry", key="inventory_search").strip().casefold()
        rows = [b for b in basis["batteries"] if not query or query in b["asset_id"].casefold()
                or query in str(b.get("chemistry", "")).casefold()]
        st.caption(f"{len(rows)} of {len(basis['batteries'])} batteries · {'Selected snapshot' if result else 'Applied scenario'}")
        if rows:
            table(rows)
        else:
            st.info("No batteries match your search. Try another ID or chemistry.")
    st.subheader("Recent activity")
    for r in reversed(history[-5:]):
        with st.container(key=f"activity_{r['run_id']}"):
            info, open_run = st.columns([4, 1])
            info.write(f"**{mode_label(r['mode'])}** · {r['status']}")
            basis_label = "Current inputs" if current_basis(r, scenario) else "Historical inputs"
            info.caption(f"{r['scenario']['scenario_id']} · {r['run_id'][:8]} · {basis_label}")
            open_run.button("Open run", key=f"review_{r['run_id']}", on_click=review_run,
                            args=(r["run_id"],), width="stretch")
    st.caption("Latest five runs shown. All session snapshots remain in Results & comparison." if history
               else "Completed assessments and allocation plans will appear here.")
