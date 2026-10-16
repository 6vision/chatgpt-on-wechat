import json
import pytest
from models import model_catalog


@pytest.mark.parametrize("reader", ["get_catalog", "get_catalog_map", "resolve_model_meta"])
def test_returned_capabilities_cannot_change_cached_catalog(tmp_path, monkeypatch, reader):
    path = tmp_path / "models.json"
    path.write_text(
        json.dumps(
            {
                "providers": {
                    "custom:test": {"overrides": [{"name": "model", "capabilities": ["text", "vision"]}], "hidden": []}
                }
            }
        )
    )
    monkeypatch.setattr(model_catalog, "_store_path", lambda: str(path))
    monkeypatch.setattr(model_catalog, "_cache", None)
    if reader == "get_catalog":
        entry = model_catalog.get_catalog("custom:test")[0]
    elif reader == "get_catalog_map":
        entry = model_catalog.get_catalog_map()["custom:test"][0]
    else:
        entry = model_catalog.resolve_model_meta("custom:test", "model")
    entry["capabilities"].clear()
    entry["name"] = "changed"
    assert model_catalog.get_catalog("custom:test")[0] == {"name": "model", "capabilities": ["text", "vision"]}
    assert json.loads(path.read_text())["providers"]["custom:test"]["overrides"][0]["capabilities"] == [
        "text",
        "vision",
    ]
