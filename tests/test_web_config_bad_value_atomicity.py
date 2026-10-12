# encoding:utf-8
"""A config save rejected over one bad value leaves the live config untouched."""

import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import channel.web.api.config as config_api


def _save(tmp_path, live, updates):
    with patch.object(config_api, "_require_auth", lambda: None), \
            patch.object(config_api.web, "header", lambda *a, **k: None), \
            patch.object(config_api.web, "data", lambda: json.dumps({"updates": updates}).encode()), \
            patch.object(config_api, "conf", lambda: live), \
            patch.object(config_api, "get_data_root", lambda: str(tmp_path)), \
            patch.object(config_api, "_read_config_file_for_write", lambda: dict(live)):
        return json.loads(config_api.ConfigHandler().POST())["status"]


def test_rejected_save_does_not_apply_earlier_keys(tmp_path):
    live = {"model": "old-model", "agent_max_steps": 20}

    assert _save(tmp_path, live, {"model": "new-model", "agent_max_steps": ""}) == "error"
    assert live == {"model": "old-model", "agent_max_steps": 20}


def test_accepted_save_still_applies(tmp_path):
    live = {"model": "old-model", "agent_max_steps": 20}

    assert _save(tmp_path, live, {"model": "new-model", "agent_max_steps": 30}) == "success"
    assert live["model"] == "new-model" and live["agent_max_steps"] == 30
