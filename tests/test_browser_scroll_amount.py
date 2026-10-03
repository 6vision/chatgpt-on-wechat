# encoding:utf-8
"""Browser scroll distance comes from `amount`, never from `timeout`."""

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.tools.browser.browser_tool import BrowserTool


@pytest.mark.parametrize("args, expected", [
    ({"direction": "down", "timeout": 10000}, 500),
    ({"direction": "down", "amount": 250, "timeout": 10000}, 250),
])
def test_scroll_distance(args, expected):
    tool = BrowserTool({})
    tool._service = MagicMock()
    tool._service.scroll.return_value = {"scrolled": "down", "scrollY": 0, "scrollHeight": 9000}

    assert tool._do_scroll(args).status == "success"
    assert tool._service.scroll.call_args.kwargs.get("amount", 500) == expected


def test_schema_advertises_amount():
    assert "amount" in BrowserTool.params["properties"]
