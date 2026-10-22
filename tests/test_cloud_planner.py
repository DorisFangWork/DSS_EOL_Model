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
    assert any("Synthetic examples" in item.value for item in app.info)
    app.button(key="run").click().run(timeout=30)
    assert not app.exception
    assert app.metric[0].value == "89,082.37"
    assert all(button.label != "Save run to local history" for button in app.button)
    assert {b.label for b in app.get("download_button")} == {
        "Download current scenario", "Download eligibility evidence", "Download complete run"}
    app.selectbox(key="example").set_value("Two-pack capacity example").run()
    for mode in ("Battery admissibility", "Destination determination", "Flow allocation — Model 0", "Integrated decision"):
        app.radio(key="mode").set_value(mode).run()
        if mode == "Flow allocation — Model 0":
            assert len(app.get("file_uploader")) == 0
            app.button(key="prepare").click().run()
        app.button(key="run").click().run(timeout=30)
        assert not app.exception and not app.error
        if mode in ("Flow allocation — Model 0", "Integrated decision"):
            assert app.metric[0].value == "17.00"
