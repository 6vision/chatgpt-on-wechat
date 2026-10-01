"""Keys shipped in config-template.json must be registered in available_setting.

Environment variables only override registered keys, so a template key missing
from available_setting cannot be configured on env-only deployments (Docker,
Railway): the variable is silently ignored.
"""
import json
from pathlib import Path

import config as config_module


def test_every_template_key_is_registered():
    template_path = Path(config_module.get_config_template_path())
    template = json.loads(template_path.read_text(encoding="utf-8"))

    missing = sorted(key for key in template if key not in config_module.available_setting)

    assert missing == []


def test_external_api_token_can_be_set_from_the_environment(tmp_path, monkeypatch):
    # An empty data dir makes load_config fall back to config-template.json.
    monkeypatch.setenv("COW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EXTERNAL_API_TOKEN", "sk-test-token")
    previous = config_module.config
    try:
        config_module.load_config()
        assert config_module.conf().get("external_api_token") == "sk-test-token"
    finally:
        config_module.config = previous
