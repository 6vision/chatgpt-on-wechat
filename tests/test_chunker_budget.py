"""Keep line-based memory chunks within their estimated token budget."""

import pytest

from agent.memory.chunker import TextChunker


@pytest.mark.parametrize("text", [
    "1234\n5678\n9abc",  # separators count toward the budget
    "ab\ncd\n" + "x" * 11,  # overlap must leave room for the incoming line
    "a\n" * 20,  # many short lines have significant separator overhead
])
def test_chunks_fit_budget_and_keep_source_line_ranges(text):
    chunker = TextChunker(max_tokens=3, overlap_tokens=2)
    chunks = chunker.chunk_text(text)
    lines = text.split("\n")

    assert chunks
    covered = set()
    for chunk in chunks:
        assert len(chunk.text) <= 12
        assert chunk.text == "\n".join(lines[chunk.start_line - 1:chunk.end_line])
        covered.update(range(chunk.start_line, chunk.end_line + 1))
    assert {i for i, line in enumerate(lines, 1) if line.strip()} <= covered


def test_overlap_keeps_the_tail_when_it_fits():
    chunks = TextChunker(max_tokens=4, overlap_tokens=1).chunk_text("aaaa\nbbbb\ncccc\ndddd")
    assert [(c.text, c.start_line, c.end_line) for c in chunks] == [
        ("aaaa\nbbbb\ncccc", 1, 3),
        ("cccc\ndddd", 3, 4),
    ]


def test_long_line_fragments_and_neighbor_lines_fit_budget():
    chunks = TextChunker(max_tokens=3).chunk_text("before\n" + "x" * 25 + "\nafter")
    assert [c.text for c in chunks] == ["before", "x" * 12, "x" * 12, "x", "after"]
    assert [(c.start_line, c.end_line) for c in chunks] == [(1, 1), (2, 2), (2, 2), (2, 2), (3, 3)]
