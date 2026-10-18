"""Direct HTTPS config: a typo in the cert path must fail startup loudly,
never silently serve plain HTTP instead."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from channel.web.core.tls import resolve_tls_config  # noqa: E402


def test_tls_disabled_returns_no_paths():
    assert resolve_tls_config(False, "", "") == (None, None)
    # Stale paths must not matter while the feature is off.
    assert resolve_tls_config(False, "/nope/cert.pem", "/nope/key.pem") == (None, None)


def test_tls_enabled_without_certfile_fails_fast():
    with pytest.raises(ValueError, match="web_ssl_certfile"):
        resolve_tls_config(True, "", "/some/key.pem")


def test_tls_enabled_without_keyfile_fails_fast():
    with pytest.raises(ValueError, match="web_ssl_keyfile"):
        resolve_tls_config(True, "/some/cert.pem", "")


def test_tls_enabled_with_missing_files_fails_fast(tmp_path):
    missing = str(tmp_path / "cert.pem")
    with pytest.raises(ValueError, match="web_ssl_certfile"):
        resolve_tls_config(True, missing, missing)


def test_tls_enabled_with_real_files_returns_expanded_paths(tmp_path):
    cert = tmp_path / "fullchain.pem"
    key = tmp_path / "privkey.pem"
    cert.write_text("cert")
    key.write_text("key")
    got_cert, got_key = resolve_tls_config(True, str(cert), str(key))
    assert got_cert == str(cert)
    assert got_key == str(key)
