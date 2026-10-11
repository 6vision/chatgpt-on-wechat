"""A malformed provider entry must not prevent reading healthy model catalogs."""
import json

import pytest

from models import model_catalog


@pytest.mark.parametrize("bad", [1, True, 3.5, "model", {"name": "wrong-container"}])
def test_invalid_overrides_container_is_ignored(monkeypatch, tmp_path, bad):
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"providers": {
        "damaged": {"overrides": bad, "hidden": ["retired"]},
        "healthy": {"overrides": [{"name": "use-me"}], "hidden": []},
    }}))
    monkeypatch.setattr(model_catalog, "_store_path", lambda: str(path))
    store = model_catalog._read_store()["providers"]
    assert store["damaged"] == {"overrides": [], "hidden": ["retired"]}
    assert store["healthy"]["overrides"][0]["name"] == "use-me"


@pytest.mark.parametrize("bad", [1, True, 3.5, "retired", {"retired": True}])
def test_invalid_tombstone_container_is_ignored(monkeypatch, tmp_path, bad):
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"providers": {"p": {"overrides": [{"name": "keep"}], "hidden": bad}}}))
    monkeypatch.setattr(model_catalog, "_store_path", lambda: str(path))
    assert model_catalog._read_store()["providers"]["p"] == {
        "overrides": [{"name": "keep", "capabilities": ["text"]}], "hidden": []}


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_nonfinite_limits_do_not_break_store_healing(monkeypatch, tmp_path, value):
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"providers": {"p": {"overrides": [
        {"name": "broken", "context_window": value}, {"name": "keep"}], "hidden": []}}}))
    monkeypatch.setattr(model_catalog, "_store_path", lambda: str(path))
    assert [entry["name"] for entry in model_catalog._read_store()["providers"]["p"]["overrides"]] == ["keep"]
