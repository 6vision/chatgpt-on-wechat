"""MemoryService.list_files clamps out-of-range paging and dispatch validates string values."""

import pytest

from agent.memory.service import MemoryService


@pytest.fixture
def service(tmp_path):
    (tmp_path / "memory").mkdir()
    for day in ("01", "02", "03", "04", "05"):
        (tmp_path / "memory" / f"2026-10-{day}.md").write_text("note", encoding="utf-8")
    return MemoryService(str(tmp_path))


def _names(result):
    return [f["filename"] for f in result["list"]]


@pytest.mark.parametrize("page, page_size, expected_page, expected_size, names", [
    (1, 2, 1, 2, ["2026-10-05.md", "2026-10-04.md"]),
    (2, 2, 2, 2, ["2026-10-03.md", "2026-10-02.md"]),
    (0, 2, 1, 2, ["2026-10-05.md", "2026-10-04.md"]),
    (-1, 2, 1, 2, ["2026-10-05.md", "2026-10-04.md"]),
    (1, -1, 1, 1, ["2026-10-05.md"]),
    (1, 0, 1, 1, ["2026-10-05.md"]),
])
def test_list_files_clamps_page_and_page_size(service, page, page_size, expected_page, expected_size, names):
    result = service.list_files(page=page, page_size=page_size)
    assert (result["page"], result["page_size"], result["total"]) == (expected_page, expected_size, 5)
    assert _names(result) == names


def test_oversized_page_size_is_capped(service):
    assert service.list_files(page=1, page_size=10 ** 6)["page_size"] == 200


def test_walking_pages_reaches_every_file_once(service):
    seen = [name for page in range(1, 5) for name in _names(service.list_files(page=page, page_size=2))]
    assert len(seen) == len(set(seen)) == 5


def test_dispatch_accepts_string_page_numbers(service):
    result = service.dispatch("list", {"page": "2", "page_size": "2"})
    assert result["code"] == 200
    assert _names(result["payload"]) == ["2026-10-03.md", "2026-10-02.md"]


@pytest.mark.parametrize("payload", [{"page": "x", "page_size": "2"}, {"page": 1, "page_size": None}])
def test_dispatch_rejects_non_numeric_paging(service, payload):
    result = service.dispatch("list", payload)
    assert result["code"] == 400
    assert result["payload"] is None
    assert "page and page_size" in result["message"]
