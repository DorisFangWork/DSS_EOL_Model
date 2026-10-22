from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


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
    assert app.radio(key="page").value == "Dashboard"
    app.radio(key="page").set_value("Decision workspace").run()
    app.button(key="run").click().run(timeout=30)
    assert not app.exception
    assert app.metric[0].value == "89,082.37"
    assert all(button.label != "Save run to local history" for button in app.button)
    assert {b.label for b in app.get("download_button")} == {
        "Download current scenario", "Download eligibility evidence", "Download complete run"}
    app.selectbox(key="example").set_value("Two-pack capacity example").run()
    for mode in ("Battery admissibility", "Destination determination", "Allocation planning", "Integrated decision"):
        app.radio(key="page").set_value("Decision workspace").run()
        app.radio(key="mode").set_value(mode).run()
        if mode == "Allocation planning":
            assert len(app.get("file_uploader")) == 0
            app.button(key="prepare").click().run()
        app.button(key="run").click().run(timeout=30)
        assert not app.exception and not app.error
        assert app.radio(key="page").value == "Results & comparison"
        if mode in ("Allocation planning", "Integrated decision"):
            assert app.metric[0].value == "17.00"
    for page in ("Dashboard", "Configuration", "Model & assumptions", "Results & comparison"):
        app.radio(key="page").set_value(page).run()
        assert not app.exception and not app.error
        assert len(app.get("file_uploader")) == 0
        assert len(app.text_area) == 0


def test_configuration_apply_history_comparison_and_stale_evidence():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_file(str(ROOT / "planner/cloud_app.py")).run(timeout=30)
    app.selectbox(key="example").set_value("Two-pack capacity example").run()
    app.button(key="open_allocation").click().run()
    app.button(key="run").click().run()
    assert any("requires supplied" in e.value for e in app.error)
    app.button(key="prepare").click().run()
    app.button(key="run").click().run(timeout=30)
    first = app.session_state["runs"][0]
    assert first["evaluation"]["economic_objective"] == 17
    app.radio(key="page").set_value("Configuration").run()
    capacity = next(n for n in app.number_input if n.key.startswith("cap_") and n.key.endswith("_repurpose"))
    capacity.set_value(2.0).run()
    assert app.session_state["scenario"].destinations[0].capacity == 1
    assert any("Unapplied changes" in w.value for w in app.warning)
    app.button(key="apply").click().run()
    assert app.session_state["scenario"].destinations[0].capacity == 2
    app.radio(key="page").set_value("Results & comparison").run()
    assert any("historical snapshot" in w.value for w in app.warning)
    assert app.session_state["runs"][0] == first
    app.radio(key="page").set_value("Decision workspace").run()
    assert app.radio(key="mode").value == "Allocation planning"
    assert any("Earlier evidence" in w.value for w in app.warning)
    app.button(key="run").click().run()
    assert any("requires supplied" in e.value for e in app.error)
    app.button(key="prepare").click().run()
    app.button(key="run").click().run(timeout=30)
    assert not app.exception and not app.error
    assert app.session_state["runs"][-1]["evaluation"]["economic_objective"] == 18
    assert any(m.delta == "+1.00" for m in app.metric)
    assert any(b.label == "Download comparison and snapshots" for b in app.get("download_button"))
    baseline = app.selectbox(key="baseline_run").value
    app.radio(key="page").set_value("Dashboard").run()
    app.radio(key="page").set_value("Results & comparison").run()
    assert app.selectbox(key="baseline_run").value == baseline
    app.radio(key="page").set_value("Configuration").run()
    assert next(n for n in app.number_input if n.key.startswith("cap_") and n.key.endswith("_repurpose")).value == 2


def test_admission_handoff_and_incompatible_comparison():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    from dataclasses import replace
    app = AppTest.from_file(str(ROOT / "planner/cloud_app.py")).run(timeout=30)
    app.selectbox(key="example").set_value("Two-pack capacity example").run()
    app.button(key="open_admission").click().run()
    app.button(key="run").click().run()
    app.radio(key="page").set_value("Decision workspace").run()
    app.radio(key="mode").set_value("Allocation planning").run()
    assert any("evidence matches" in s.value for s in app.success)
    app.button(key="run").click().run()
    assert app.session_state["runs"][-1]["evaluation"]["economic_objective"] == 17
    # A different horizon must not produce numeric comparison deltas.
    app.session_state["scenario"] = replace(app.session_state["scenario"], horizon="Different evaluation window")
    app.radio(key="page").set_value("Decision workspace").run()
    app.radio(key="mode").set_value("Integrated decision").run()
    app.button(key="run").click().run()
    history = app.session_state["runs"]
    app.selectbox(key="baseline_run").set_value(history[1]["run_id"]).run()
    app.selectbox(key="alternative_run").set_value(history[2]["run_id"]).run()
    assert any("matching currency and planning horizon" in w.value for w in app.warning)
    assert not any(m.delta for m in app.metric)
