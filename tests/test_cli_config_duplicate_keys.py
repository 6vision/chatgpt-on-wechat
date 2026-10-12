"""The CLI reads duplicate configuration keys as the app does."""
import pytest
from click.testing import CliRunner

from cli.commands import process
from cli.utils import load_config_json
from common import i18n


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    monkeypatch.setenv("COW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return tmp_path / "config.json"


@pytest.mark.parametrize("body,channels", [
    ('"channel_type":["terminal","web"]', ["terminal", "web"]),
    ('"channel_type":["terminal"],"channel_type":["web"]', ["terminal", "web"]),
    ('"channel_type":["web"],"channel_type":["terminal"]', ["web", "terminal"]),
    ('"channel_type":["terminal"]', ["terminal"]),
])
def test_status_and_terminal_decision_share_all_configured_channels(config_file, monkeypatch, body, channels):
    config_file.write_text('{"cow_lang":"en","model":"fixture-model",' + body + '}')
    assert load_config_json()["channel_type"] == channels
    assert process._is_terminal_only() is (channels == ["terminal"])
    monkeypatch.setattr(process, "_read_pid", lambda: None)
    previous_language = i18n.get_language()
    try:
        result = CliRunner().invoke(process.status)
    finally:
        i18n.set_language(previous_language)
    assert result.exit_code == 0
    assert "  Channel: " + ", ".join(channels) in result.output


def test_nested_keys_and_later_scalar_keep_canonical_merge_semantics(config_file):
    config_file.write_text(
        '\ufeff{"ui":{"label":"你好"},"ui":{"theme":"dark"},"model":"old","model":"new"}',
        encoding="utf-8",
    )
    assert load_config_json() == {"ui": {"label": "你好", "theme": "dark"}, "model": "new"}


@pytest.mark.parametrize("content", [None, "{unfinished"])
def test_missing_and_unreadable_config_still_return_empty(config_file, content):
    if content is not None:
        config_file.write_text(content)
    assert load_config_json() == {}


def test_app_keeps_nested_list_precedence_and_duplicate_diagnostics(config_file, monkeypatch):
    import json
    import config

    body = '{"ui":{"items":[1],"nested":{"first":true}},"ui":{"items":[2],"nested":{"second":true}},"channel_type":["web"],"channel_type":["web"],"channel_type":["terminal"]}'
    config_file.write_text(body)
    expected = {"ui": {"items": [2], "nested": {"first": True, "second": True}},
                "channel_type": ["web", "web", "terminal"]}
    warnings = []
    monkeypatch.setattr(config.logger, "warning", lambda *args: warnings.append(args))
    assert json.loads(body, object_pairs_hook=config._merge_duplicate_keys) == expected
    assert warnings == [("[INIT] config.json has duplicate keys (merged): %s", ["channel_type", "ui"])]
    assert load_config_json() == expected


@pytest.mark.parametrize("body,expected", [
    ('{"channel_type":["web","terminal"]}', {"channel_type": ["web", "terminal"]}),
    ('{"channel_type":["web"],"channel_type":["terminal"]}', {"channel_type": ["web", "terminal"]}),
])
def test_standalone_cli_reader_needs_no_app_modules(tmp_path, body, expected):
    import json
    import os
    import shutil
    import subprocess
    import sys
    from pathlib import Path
    import cli

    isolated = tmp_path / "standalone"
    isolated.mkdir()
    shutil.copytree(Path(cli.__file__).parent, isolated / "cli", ignore=shutil.ignore_patterns("__pycache__"))
    data = isolated / "data"
    data.mkdir()
    (data / "config.json").write_text(body)
    env = {"PATH": os.environ["PATH"], "HOME": str(isolated), "USERPROFILE": str(isolated),
           "COW_DATA_DIR": str(data), "PYTHONPATH": str(isolated), "PYTHONDONTWRITEBYTECODE": "1"}
    code = ('import json,sys;from cli.utils import load_config_json;'
            'print(json.dumps({"value":load_config_json(),"app":"config" in sys.modules,'
            '"common":"common" in sys.modules}))')
    result = subprocess.run([sys.executable, "-S", "-c", code], cwd=isolated, env=env,
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {"value": expected, "app": False, "common": False}
