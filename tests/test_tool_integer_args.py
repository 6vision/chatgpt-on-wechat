"""Integer tool arguments a model sends quoted ("offset": "2") are converted once,
in BaseTool.execute_tool, for every tool that declares them as integers."""

import pytest

from agent.tools.base_tool import BaseTool, ToolResult
from agent.tools.read.read import Read


class _Echo(BaseTool):
    name = "echo"
    params = {"type": "object", "properties": {"n": {"type": "integer"}, "s": {"type": "string"}}}

    def execute(self, params):
        return ToolResult.success(params)


@pytest.mark.parametrize("raw, expected", [("2", 2), (" 2 ", 2), ("2.0", 2), (2.0, 2), (2, 2)])
def test_integer_arguments_are_converted(raw, expected):
    result = _Echo().execute_tool({"n": raw, "s": "7"})
    assert result.status == "success"
    assert result.result == {"n": expected, "s": "7"}


@pytest.mark.parametrize("raw", ["two", "2.5", True])
def test_a_non_integer_is_refused_with_the_argument_name(raw):
    result = _Echo().execute_tool({"n": raw})
    assert result.status == "error"
    assert "n must be an integer" in result.result


def test_read_accepts_quoted_offset_and_limit(tmp_path):
    path = tmp_path / "f.txt"
    path.write_text("\n".join(f"line{i}" for i in range(1, 13)) + "\n", encoding="utf-8")
    tool = Read({"cwd": str(tmp_path)})

    quoted = tool.execute_tool({"path": str(path), "offset": "4", "limit": "2"})
    plain = tool.execute_tool({"path": str(path), "offset": 4, "limit": 2})

    assert quoted.status == "success", quoted.result
    assert quoted.result["content"] == plain.result["content"]
    assert quoted.result["content"].startswith("4|line4\n5|line5")


def test_memory_get_refuses_a_non_positive_num_lines():
    from agent.tools.memory.memory_get import MemoryGetTool

    tool = MemoryGetTool.__new__(MemoryGetTool)
    result = tool.execute_tool({"path": "MEMORY.md", "num_lines": "0"})
    assert result.status == "error"
    assert "num_lines must be a positive" in result.result
