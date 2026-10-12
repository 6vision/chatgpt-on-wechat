import pytest
from common.utils import split_string_by_utf8_length

@pytest.mark.parametrize("text,budget", [("abc", 0), ("abc", -1), ("中", 2), ("😀", 3)])
def test_impossible_budget_is_rejected(text, budget):
    # A split cap keeps the baseline reproduction bounded: it returns an empty
    # segment instead of advancing. Without the cap the same input hangs.
    with pytest.raises(ValueError):
        split_string_by_utf8_length(text, budget, max_split=1)

@pytest.mark.parametrize("text,budget", [("abc", 2), ("中文abc😀", 4), ("", 1)])
def test_valid_budget_preserves_text(text, budget):
    parts = split_string_by_utf8_length(text, budget)
    assert "".join(parts) == text
    assert all(0 < len(part.encode("utf-8")) <= budget for part in parts)
