"""skill_hub_url / skill_hub_api_key: which registry hub requests go to, and with what."""
import hashlib
import io
import json
import os
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from cli.commands import skill as skill_cli
from cli.utils import SKILL_HUB_API, get_skills_dir, skill_hub

REGISTRY = "https://registry.example.test/api/skills-hub"
DOWNLOAD = "https://cdn.example.test/pkg/weekly-report.zip"


@pytest.fixture
def data_dir(tmp_path):
    home, data, workspace = (tmp_path / name for name in ("home", "data", "workspace"))
    home.mkdir()
    data.mkdir()
    (workspace / "skills").mkdir(parents=True)

    def configure(**settings):
        settings.setdefault("agent_workspace", str(workspace))
        (data / "config.json").write_text(json.dumps(settings), encoding="utf-8")

    configure()
    env = {"HOME": str(home), "USERPROFILE": str(home), "COW_DATA_DIR": str(data)}
    with patch.dict(os.environ, env, clear=True):
        yield configure


class _Response:
    def __init__(self, status=200, body=None, content=b"", content_type="application/json"):
        self.status_code = status
        self._body = body
        self.content = content
        self.headers = {"Content-Type": content_type}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


def _package() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("weekly-report/SKILL.md", "---\nname: weekly-report\ndescription: Draft weekly reports\n---\n")
    return buf.getvalue()


def test_default_hub_without_settings(data_dir):
    data_dir(skill_hub_api_key="secret")
    assert skill_hub() == (SKILL_HUB_API, {})


def test_configured_registry_gets_the_key(data_dir):
    data_dir(skill_hub_url=REGISTRY + "/", skill_hub_api_key="secret")
    assert skill_hub() == (REGISTRY, {"Authorization": "Bearer secret"})


def test_provider_requests_stay_on_the_default_hub_without_the_key(data_dir):
    data_dir(skill_hub_url=REGISTRY, skill_hub_api_key="secret")
    assert skill_hub("clawhub") == (SKILL_HUB_API, {})


@pytest.mark.parametrize("url", ["ftp://x", "registry.example.test", "https://"])
def test_malformed_registry_is_ignored(data_dir, url):
    data_dir(skill_hub_url=url, skill_hub_api_key="secret")
    assert skill_hub() == (SKILL_HUB_API, {})


def test_plain_http_registry_is_honored(data_dir):
    data_dir(skill_hub_url="http://registry.example.test/hub/")
    assert skill_hub() == ("http://registry.example.test/hub", {})


def test_install_from_configured_registry_records_its_fields(data_dir):
    data_dir(skill_hub_url=REGISTRY, skill_hub_api_key="secret")
    package = _package()
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(("post", url, headers))
        return _Response(body={
            "source_type": "registry", "source_provider": "registry", "download_url": DOWNLOAD,
            "sha256": hashlib.sha256(package).hexdigest(), "display_name": "Weekly Report",
            "icon": "https://cdn.example.test/icon.png", "version": "1.2.0", "category": "market",
        })

    def fake_get(url, **kwargs):
        calls.append(("get", url, kwargs.get("headers")))
        return _Response(content=package, content_type="application/zip")

    with patch.object(requests, "post", fake_post), patch.object(requests, "get", fake_get):
        result = skill_cli.install_skill("weekly-report")

    assert result.error is None, result.error
    assert calls[0] == ("post", f"{REGISTRY}/skills/weekly-report/download", {"Authorization": "Bearer secret"})
    # The package host is not the registry, so it never sees the key.
    assert calls[1] == ("get", DOWNLOAD, None)
    config = json.loads((Path(get_skills_dir()) / "skills_config.json").read_text(encoding="utf-8"))
    entry = config["weekly-report"]
    assert entry["display_name"] == "Weekly Report"
    assert entry["icon"] == "https://cdn.example.test/icon.png"
    assert entry["version"] == "1.2.0"
    assert entry["category"] == "market"
    assert entry["description"] == "Draft weekly reports"


def test_registry_refusal_reports_its_message(data_dir):
    data_dir(skill_hub_url=REGISTRY, skill_hub_api_key="stale")

    def fake_post(url, json=None, headers=None, timeout=None):
        return _Response(status=401, body={"success": False, "message": "API key is invalid"})

    with patch.object(requests, "post", fake_post):
        result = skill_cli.install_skill("weekly-report")

    assert result.error == "Failed to fetch skill: API key is invalid"


def test_default_hub_install_keeps_its_category(data_dir):
    package = _package()

    def fake_post(url, json=None, headers=None, timeout=None):
        assert url.startswith(SKILL_HUB_API) and not headers
        return _Response(body={
            "source_type": "registry", "source_provider": "cowhub", "download_url": DOWNLOAD,
            "display_name": "Weekly Report", "category": "productivity",
        })

    with patch.object(requests, "post", fake_post), \
            patch.object(requests, "get", lambda url, **kw: _Response(content=package, content_type="application/zip")):
        result = skill_cli.install_skill("weekly-report")

    assert result.error is None, result.error
    config = json.loads((Path(get_skills_dir()) / "skills_config.json").read_text(encoding="utf-8"))
    assert config["weekly-report"]["category"] == "skill"
