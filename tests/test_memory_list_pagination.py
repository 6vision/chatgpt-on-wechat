"""Page numbers arriving from outside the process.

`list_files` turns `page` and `page_size` straight into a Python slice. That is
fine while the only caller is the web handler, which parses them itself -- but
the cloud console forwards the same two fields as whatever it was sent, and
they reach that slice unchanged. Python's slicing then applies its own
semantics: a negative index counts from the end, and a zero-width slice is
simply empty. Neither is what the caller meant, and both come back as a `200`
with a plausible-looking body, so the console cannot tell that the listing it
is rendering is not the listing it asked for.
"""

import pytest

from agent.memory.service import MemoryService

# Spelled out rather than imported: on unpatched master this module has no such
# constant, and a test module that fails to import proves nothing about the
# behaviour. The cap itself is asserted behaviourally, further down.
_PAGE_SIZE_CAP = 200


@pytest.fixture
def service(tmp_path):
    """A service over a workspace holding five daily memory files."""
    daily = tmp_path / "memory"
    daily.mkdir()
    for day in ("01", "02", "03", "04", "05"):
        (daily / f"2026-10-{day}.md").write_text("note", encoding="utf-8")
    return MemoryService(str(tmp_path))


def _names(result):
    return [f["filename"] for f in result["list"]]


def test_the_first_page_is_the_first_page(service):
    assert _names(service.list_files(page=1, page_size=2)) == [
        "2026-10-05.md", "2026-10-04.md"]


def test_a_second_page_follows_the_first(service):
    assert _names(service.list_files(page=2, page_size=2)) == [
        "2026-10-03.md", "2026-10-02.md"]


def test_page_zero_is_the_first_page_and_not_an_empty_listing(service):
    """`files[-2:0]` is empty, so this used to answer "you have no memory
    files" while reporting five of them in `total`."""
    result = service.list_files(page=0, page_size=2)

    assert result["page"] == 1
    assert len(result["list"]) == 2
    assert result["total"] == 5


def test_a_negative_page_is_the_first_page_and_not_a_middle_one(service):
    """`files[-4:-2]` is a real slice, so this used to hand back the middle of
    the listing under a page number that names no such page."""
    result = service.list_files(page=-1, page_size=2)

    assert result["page"] == 1
    assert _names(result) == ["2026-10-05.md", "2026-10-04.md"]


def test_a_negative_page_size_does_not_silently_drop_a_file(service):
    """`files[0:-1]` is every file but the last, so a bad page_size quietly
    truncated the result instead of being reported."""
    result = service.list_files(page=1, page_size=-1)

    assert result["page_size"] == 1
    assert _names(result) == ["2026-10-05.md"]


def test_a_zero_page_size_still_returns_something(service):
    result = service.list_files(page=1, page_size=0)

    assert result["page_size"] == 1
    assert len(result["list"]) == 1


def test_an_oversized_page_size_is_capped(service):
    """One page of a listing should stay one page however large the ask."""
    result = service.list_files(page=1, page_size=10 ** 6)

    assert result["page_size"] == _PAGE_SIZE_CAP


def test_every_page_is_reachable_when_walked_one_at_a_time(service):
    """The clamp must not pin the walk to page one: paging through with a
    normal page_size has to reach every file exactly once."""
    seen = []
    page = 1
    while True:
        result = service.list_files(page=page, page_size=2)
        names = _names(result)
        if not names:
            break
        seen.extend(names)
        page += 1

    assert sorted(seen) == sorted(set(seen)), "a file came back twice"
    assert len(seen) == 5


def test_the_cloud_console_can_send_the_page_numbers_as_strings(service):
    """`on_memory` hands the payload straight to `dispatch`, so the fields
    arrive as strings even though they are documented as numbers."""
    result = service.dispatch("list", {"page": "2", "page_size": "2"})

    assert result["code"] == 200
    assert [f["filename"] for f in result["payload"]["list"]] == [
        "2026-10-03.md", "2026-10-02.md"]


def test_a_non_numeric_page_is_a_four_hundred_not_a_server_error(service):
    """The sibling `on_history` handler answers this exact case with a 400 and
    a message naming the fields; this one used to let the arithmetic fail and
    report the TypeError as a 500."""
    result = service.dispatch("list", {"page": "x", "page_size": "2"})

    assert result["code"] == 400
    assert result["payload"] is None
    assert "page and page_size" in result["message"]


def test_a_missing_page_size_is_reported_rather_than_defaulted_silently(service):
    """`None` is not a number either, and defaulting it would hide a caller
    that sent the field with no value."""
    result = service.dispatch("list", {"page": 1, "page_size": None})

    assert result["code"] == 400
