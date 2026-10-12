# encoding:utf-8
"""Env-var config overrides are logged with secret values masked."""

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as config_module


def _override_log_lines(monkeypatch, tmp_path, env_name, value):
    monkeypatch.setenv("COW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(env_name, value)
    # load_config rebinds the module-level singleton; restore the original after.
    monkeypatch.setattr(config_module, "config", config_module.config)
    with patch.object(config_module, "logger") as logger:
        config_module.load_config()
    assert config_module.conf().get(env_name.lower()) == value
    return [str(c.args[0]) for c in logger.info.call_args_list
            if "override config by environ" in str(c.args[0])]


@pytest.mark.parametrize("env_name,value,visible", [
    ("DINGTALK_CLIENT_SECRET", "sentinel-client-secret-9f2b41aa", False),
    ("MODEL", "sentinel-model-7731", True),
])
def test_override_log_masks_secrets_only(monkeypatch, tmp_path, env_name, value, visible):
    lines = [line for line in _override_log_lines(monkeypatch, tmp_path, env_name, value)
             if env_name.lower() in line]
    assert lines
    assert any(value in line for line in lines) is visible
