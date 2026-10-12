# encoding:utf-8
"""A non-numeric environment override for a numeric key is ignored, not stored as text."""

import os
import shutil
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as config_module


def _load_with_env(**env):
    data_dir = tempfile.mkdtemp(prefix="cow-env-override-")
    previous = config_module.config
    try:
        with patch.dict(os.environ, {"COW_DATA_DIR": data_dir, **env}, clear=False):
            config_module.load_config()
            return config_module.conf()
    finally:
        config_module.config = previous
        shutil.rmtree(data_dir, ignore_errors=True)


def test_numeric_override_with_a_suffix_is_ignored():
    assert _load_with_env(REQUEST_TIMEOUT="180s").get("request_timeout", 180) == 180
    assert _load_with_env(TEMPERATURE="warm").get("temperature", 0.9) == 0.9


def test_the_warning_names_the_key_but_not_the_value(caplog):
    with caplog.at_level("WARNING", logger="log"):
        _load_with_env(REQUEST_TIMEOUT="180s-s3cr3t")
    assert "request_timeout" in caplog.text
    assert "s3cr3t" not in caplog.text


def test_other_overrides_are_unchanged():
    conf = _load_with_env(REQUEST_TIMEOUT="90", TEXT_TO_VOICE_MODEL="tts-1-hd", SPEECH_RECOGNITION="false")
    assert conf.get("request_timeout") == 90
    assert conf.get("text_to_voice_model") == "tts-1-hd"
    assert conf.get("speech_recognition") is False
