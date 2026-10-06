"""Opt-in real browser proof that snapshot refs use normal input actions.

Run with COW_BROWSER_NATIVE_TEST=1 and an installed system Chrome/Edge plus
Playwright. This never installs a browser or opens the user's existing profile.
"""

import os
import re

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("COW_BROWSER_NATIVE_TEST") != "1", reason="opt-in installed browser test")


@pytest.mark.parametrize("action,kind,disabled", [
    ("click", "button", False), ("click", "button", True),
    ("fill", "input", False), ("fill", "input", True),
    ("fill", "div", False),
    ("select", "select", False), ("select", "select", True),
])
def test_ref_actions_follow_browser_editability(tmp_path, action, kind, disabled):
    pytest.importorskip("playwright.sync_api")
    from agent.tools.browser.browser_env import detect_system_chrome
    from agent.tools.browser.browser_tool import BrowserTool

    if detect_system_chrome() is None:
        pytest.skip("no installed system Chrome/Edge")
    disabled_attr = " disabled" if disabled else ""
    if kind == "button":
        control = f'<button onclick="window.events++"{disabled_attr}>Click target</button>'
    elif kind == "input":
        control = f'<input value="initial" oninput="window.events++"{disabled_attr}>'
    elif kind == "div":
        control = '<div contenteditable="true" oninput="window.events++">initial</div>'
    else:
        control = f'<select onchange="window.events++"{disabled_attr}><option value="initial">Initial</option><option value="new">New</option></select>'
    page = tmp_path / "controls.html"
    page.write_text(f'<html><body><script>window.events=0</script>{control}</body></html>', encoding="utf-8")
    previous = BrowserTool._shared_service
    BrowserTool._shared_service = None
    tool = BrowserTool({"cwd": str(tmp_path), "user_data_dir": str(tmp_path / "profile"), "headless": True, "idle_timeout": 0, "startup_timeout": 20, "engine": "system-chrome"})
    try:
        navigation = tool.execute({"action": "navigate", "url": page.as_uri(), "timeout": 15000})
        assert navigation.status == "success", navigation.result
        match = re.search(r"\[(\d+)\] " + kind + r"\b", navigation.result)
        assert match, navigation.result
        outcome = tool.execute({"action": action, "ref": int(match.group(1)), "text": "new", "value": "new", "timeout": 500})
        assert outcome.status == ("error" if disabled else "success"), outcome.result
        state = tool._get_service().evaluate("() => ({events: window.events, value: document.querySelector('input,select')?.value, text: document.querySelector('[contenteditable]')?.textContent})")["result"]
        if disabled:
            assert state["events"] == 0
            if kind != "button":
                assert state["value"] == "initial"
        elif kind == "button":
            assert state["events"] == 1
        else:
            assert state["events"] > 0
            assert state["text" if kind == "div" else "value"] == "new"
    finally:
        if tool._service is not None:
            tool._service.close()
        BrowserTool._shared_service = previous
