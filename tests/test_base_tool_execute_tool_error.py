"""Regression: BaseTool.execute_tool must return a failed ToolResult, never None,
so the caller can read .status and the model sees the real cause."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.tools.base_tool import BaseTool, ToolResult  # noqa: E402


class BoomTool(BaseTool):
    name = "boom"
    description = "a tool whose execute() raises"
    params = {"type": "object", "properties": {}}

    def execute(self, params):
        raise RuntimeError("upstream refused the connection")


class OkTool(BaseTool):
    name = "ok"
    description = "a tool that succeeds"
    params = {"type": "object", "properties": {}}

    def execute(self, params):
        return ToolResult.success("done")


class TestExecuteToolReturnsAResult:
    def test_a_raising_tool_yields_a_failed_result_not_none(self):
        result = BoomTool().execute_tool({})
        assert result is not None, "execute_tool returned None; the caller would raise AttributeError"
        assert result.status == "error"

    def test_the_real_cause_reaches_the_model(self):
        result = BoomTool().execute_tool({})
        # The old code returned None, so the caller raised
        # AttributeError('NoneType' object has no attribute 'status') and the
        # original message was lost. The actual cause must be in the result.
        assert "upstream refused the connection" in str(result.result)
        assert "RuntimeError" in str(result.result)
        assert "NoneType" not in str(result.result)

    def test_the_caller_can_read_status_without_raising(self):
        result = BoomTool().execute_tool({})
        # Exactly what agent_stream.py:2156-2160 does with the return value.
        payload = {"status": result.status, "result": result.result,
                   "execution_time": 0}
        assert payload["status"] == "error"

    def test_a_succeeding_tool_is_untouched(self):
        result = OkTool().execute_tool({})
        assert result.status == "success"
        assert result.result == "done"
