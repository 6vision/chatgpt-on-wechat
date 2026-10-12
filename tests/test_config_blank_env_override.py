"""Blank environment placeholders must not wipe settings saved in config.json."""
import json
import os

import config


def _load(tmp_path, monkeypatch, saved, env):
    (tmp_path / "config.json").write_text(json.dumps(saved))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("COW_DATA_DIR", str(tmp_path))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    config.load_config()
    return config.conf()


def test_blank_env_keeps_saved_values(tmp_path, monkeypatch):
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    conf = _load(tmp_path, monkeypatch,
                 {"deepseek_api_key": "sk-saved", "feishu_app_id": "cli_saved"},
                 {"DEEPSEEK_API_KEY": "", "FEISHU_APP_ID": ""})
    assert conf.get("deepseek_api_key") == "sk-saved"
    assert conf.get("feishu_app_id") == "cli_saved"
    assert os.environ["FEISHU_APP_ID"] == "cli_saved"


def test_non_blank_env_still_overrides(tmp_path, monkeypatch):
    conf = _load(tmp_path, monkeypatch,
                 {"deepseek_api_key": "sk-saved", "model": "saved-model"},
                 {"DEEPSEEK_API_KEY": "sk-env", "MODEL": "env-model"})
    assert conf.get("deepseek_api_key") == "sk-env"
    assert conf.get("model") == "env-model"
