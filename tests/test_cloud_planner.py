from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_console_dashboard_snapshot_summary_and_scenario_switch():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(ROOT / "planner/cloud_app.py")).run(timeout=30)
    assert not app.metric  # Context is a compact strip, not outcome cards.
    app.selectbox(key="example").set_value("Two-pack capacity example").run()
    app.button(key="nav_Decision workspace").click().run()
    assert not any(b.key == "run" for b in app.button)
    app.button(key="choose_Integrated decision").click().run()
    app.button(key="run").click().run(timeout=30)
    snapshot = app.session_state["runs"][-1]
    app.button(key="nav_Dashboard").click().run()
    assert app.metric[0].value == "17.00"
    assert len([b for b in app.button if b.key in {"open_admission", "open_destination", "open_allocation"}]) == 3
    app.selectbox(key="example").set_value("Synthetic 60-pack fleet").run()
    assert any("earlier scenario" in w.value for w in app.warning)
    assert app.metric[0].value == "17.00"  # Historical values retain their snapshot.
    assert app.session_state["runs"][-1] == snapshot
    assert not app.exception


def test_question_cards_select_without_running_and_retain_selection():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(ROOT / "planner/cloud_app.py")).run(timeout=30)
    app.button(key="nav_Decision workspace").click().run()
    assert not app.radio
    assert not any(b.key == "run" for b in app.button)
    assert len([b for b in app.button if b.key and b.key.startswith("choose_")]) == 4
    for label in ("Battery admissibility", "Destination determination", "Allocation planning", "Integrated decision"):
        app.button(key=f"choose_{label}").click().run()
        assert app.session_state["mode"] == label
        assert app.button(key=f"choose_{label}").label.startswith("Selected")
        assert not app.session_state["runs"]
    app.button(key="nav_Dashboard").click().run()
    app.button(key="nav_Decision workspace").click().run()
    assert app.button(key="choose_Integrated decision").label.startswith("Selected")
    assert not app.exception


def test_recent_runs_latest_review_comparison_defaults_and_inventory_search():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(ROOT / "planner/cloud_app.py")).run(timeout=30)
    app.selectbox(key="example").set_value("Two-pack capacity example").run()
    app.text_input(key="inventory_search").set_value("nmc").run()
    assert any("2 of 2 batteries" in c.value for c in app.caption)
    app.text_input(key="inventory_search").set_value("missing-id").run()
    assert any("No batteries match" in i.value for i in app.info)
    app.text_input(key="inventory_search").set_value("A").run()
    assert any("1 of 2 batteries" in c.value for c in app.caption)
    app.button(key="open_admission").click().run()
    app.button(key="run").click().run()
    for _ in range(2):
        app.button(key="nav_Decision workspace").click().run()
        app.button(key="choose_Integrated decision").click().run()
        app.button(key="run").click().run()
    history = app.session_state["runs"]
    assert app.selectbox(key="baseline_run").value == history[1]["run_id"]
    assert app.selectbox(key="alternative_run").value == history[2]["run_id"]
    app.selectbox(key="selected_run").set_value(history[0]["run_id"]).run()
    app.button(key="nav_Dashboard").click().run()
    app.button(key="review_latest").click().run()
    assert app.selectbox(key="selected_run").value == history[2]["run_id"]
    app.button(key="nav_Dashboard").click().run()
    app.button(key=f"review_{history[0]['run_id']}").click().run()
    assert app.selectbox(key="selected_run").value == history[0]["run_id"]
    assert not app.exception and not app.error


def test_product_overview_navigation_and_action_labels():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(ROOT / "planner/cloud_app.py")).run(timeout=30)
    assert app.session_state["page"] == "Dashboard"
    assert not any(r.key == "page" for r in app.radio)
    assert len([b for b in app.button if b.key and b.key.startswith("nav_")]) == 6
    app.button(key="nav_Overview").click().run()
    next(b for b in app.button if b.label == "Open planning dashboard").click().run()
    assert app.session_state["page"] == "Dashboard"
    for mode, action in [("admission", "Assess battery eligibility"),
                         ("destination", "Compare destination options"),
                         ("allocation", "Create allocation plan")]:
        app.button(key="nav_" + "Overview").click().run()
        app.button(key=f"open_{mode}").click().run()
        assert app.session_state["page"] == "Decision workspace"
        assert app.button(key="run").label == action
        assert not app.exception
    app.button(key="nav_" + "Model & assumptions").click().run()
    assert any("original example" in c.value for c in app.caption)


def test_cloud_synthetic_modes_and_downloads_without_local_storage(monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    import dss.storage

    def forbidden_store(*args, **kwargs):
        pytest.fail("cloud app attempted to access persistent local history")
    monkeypatch.setattr(dss.storage, "RunStore", forbidden_store)
    app = AppTest.from_file(str(ROOT / "planner/cloud_app.py")).run(timeout=30)
    assert not app.exception
    assert len(app.get("file_uploader")) == 0
    assert len(app.text_area) == 0
    assert any("Synthetic examples" in item.value for item in app.caption)
    assert app.session_state["page"] == "Dashboard"
    app.button(key="nav_" + "Decision workspace").click().run()
    app.button(key="choose_Integrated decision").click().run()
    app.button(key="run").click().run(timeout=30)
    assert not app.exception
    assert app.metric[0].value == "89,082.37"
    assert all(button.label != "Save run to local history" for button in app.button)
    assert {b.label for b in app.get("download_button")} == {
        "Download current scenario", "Download eligibility evidence", "Download complete run"}
    app.selectbox(key="example").set_value("Two-pack capacity example").run()
    for mode in ("Battery admissibility", "Destination determination", "Allocation planning", "Integrated decision"):
        app.button(key="nav_" + "Decision workspace").click().run()
        app.button(key=f"choose_{mode}").click().run()
        if mode == "Allocation planning":
            assert len(app.get("file_uploader")) == 0
            app.button(key="prepare").click().run()
        app.button(key="run").click().run(timeout=30)
        assert not app.exception and not app.error
        assert app.session_state["page"] == "Results & comparison"
        expected_tab = {"Battery admissibility": "Admissibility", "Destination determination": "Destination comparison",
                        "Allocation planning": "Allocation details", "Integrated decision": "Allocation details"}[mode]
        assert app.tabs[1].label == expected_tab
        if mode in ("Battery admissibility", "Destination determination"):
            assert sum(int(m.value) for m in app.metric) == 4
        if mode in ("Allocation planning", "Integrated decision"):
            assert app.metric[0].value == "17.00"
    for page in ("Overview", "Dashboard", "Configuration", "Model & assumptions", "Results & comparison"):
        app.button(key="nav_" + page).click().run()
        assert not app.exception and not app.error
        assert len(app.get("file_uploader")) == 0
        assert len(app.text_area) == 0


def test_configuration_apply_history_comparison_and_stale_evidence():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(ROOT / "planner/cloud_app.py")).run(timeout=30)
    app.selectbox(key="example").set_value("Two-pack capacity example").run()
    app.button(key="open_allocation").click().run()
    assert app.button(key="run").disabled
    assert not app.session_state["runs"]
    app.button(key="prepare").click().run()
    app.button(key="run").click().run(timeout=30)
    first = app.session_state["runs"][0]
    assert first["evaluation"]["economic_objective"] == 17
    app.button(key="nav_" + "Configuration").click().run()
    capacity = next(n for n in app.number_input if n.key.startswith("cap_") and n.key.endswith("_repurpose"))
    capacity.set_value(2.0).run()
    assert app.session_state["scenario"].destinations[0].capacity == 1
    assert any("Unapplied changes" in w.value for w in app.warning)
    app.button(key="apply").click().run()
    assert app.session_state["scenario"].destinations[0].capacity == 2
    app.button(key="nav_" + "Results & comparison").click().run()
    assert any("historical snapshot" in w.value for w in app.warning)
    assert app.session_state["runs"][0] == first
    app.button(key="nav_" + "Decision workspace").click().run()
    assert app.session_state["mode"] == "Allocation planning"
    assert any("Earlier evidence" in w.value for w in app.warning)
    assert app.button(key="run").disabled
    assert len(app.session_state["runs"]) == 1
    app.button(key="prepare").click().run()
    app.button(key="run").click().run(timeout=30)
    assert not app.exception and not app.error
    assert app.session_state["runs"][-1]["evaluation"]["economic_objective"] == 18
    assert any(m.delta == "+1.00" for m in app.metric)
    assert any(b.label == "Download comparison and snapshots" for b in app.get("download_button"))
    baseline = app.selectbox(key="baseline_run").value
    app.button(key="nav_" + "Dashboard").click().run()
    app.button(key="nav_" + "Results & comparison").click().run()
    assert app.selectbox(key="baseline_run").value == baseline
    app.button(key="nav_" + "Configuration").click().run()
    assert next(n for n in app.number_input if n.key.startswith("cap_") and n.key.endswith("_repurpose")).value == 2


def test_admission_handoff_and_incompatible_comparison():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    from dataclasses import replace
    app = AppTest.from_file(str(ROOT / "planner/cloud_app.py")).run(timeout=30)
    app.selectbox(key="example").set_value("Two-pack capacity example").run()
    app.button(key="open_admission").click().run()
    app.button(key="run").click().run()
    app.button(key="nav_" + "Decision workspace").click().run()
    app.button(key="choose_Allocation planning").click().run()
    assert any("evidence matches" in s.value for s in app.success)
    app.button(key="run").click().run()
    assert app.session_state["runs"][-1]["evaluation"]["economic_objective"] == 17
    # A different horizon must not produce numeric comparison deltas.
    app.session_state["scenario"] = replace(app.session_state["scenario"], horizon="Different evaluation window")
    app.button(key="nav_" + "Decision workspace").click().run()
    app.button(key="choose_Integrated decision").click().run()
    app.button(key="run").click().run()
    history = app.session_state["runs"]
    app.selectbox(key="baseline_run").set_value(history[1]["run_id"]).run()
    app.selectbox(key="alternative_run").set_value(history[2]["run_id"]).run()
    assert any("matching currency and planning horizon" in w.value for w in app.warning)
    assert not any(m.delta for m in app.metric)
