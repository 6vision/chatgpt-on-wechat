"""Direct HTTPS for the web console (opt-in via web_https_enabled)."""

import os
from typing import Optional, Tuple


def resolve_tls_config(
    https_enabled: bool,
    certfile: str,
    keyfile: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Validate the direct-HTTPS config; return ``(certfile, keyfile)``.

    Returns ``(None, None)`` when HTTPS is disabled. Raises ``ValueError``
    with an actionable message when it is enabled but misconfigured, so a
    bad path fails fast at startup instead of serving plain HTTP silently.
    """
    if not https_enabled:
        return None, None
    certfile = (certfile or "").strip()
    keyfile = (keyfile or "").strip()
    if not certfile:
        raise ValueError(
            "web_https_enabled is true but web_ssl_certfile is empty; "
            "set it to the PEM certificate file (full chain recommended)"
        )
    if not keyfile:
        raise ValueError(
            "web_https_enabled is true but web_ssl_keyfile is empty; "
            "set it to the PEM private key file"
        )
    for label, path in (("web_ssl_certfile", certfile), ("web_ssl_keyfile", keyfile)):
        expanded = os.path.expanduser(path)
        if not (os.path.isfile(expanded) and os.access(expanded, os.R_OK)):
            raise ValueError(
                f"{label} points at {path!r}, which is not a readable file"
            )
    return os.path.expanduser(certfile), os.path.expanduser(keyfile)
