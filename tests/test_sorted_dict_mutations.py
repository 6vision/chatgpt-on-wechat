import pytest
from common.sorted_dict import SortedDict

def ordered():
    return SortedDict(lambda key, value: value, {"low": 1, "high": 9}, reverse=True)

def test_clear_then_reload_has_only_current_plugins():
    plugins = ordered()
    assert list(plugins) == ["high", "low"]
    plugins.clear()
    plugins["fresh"] = 3
    assert plugins.items() == [("fresh", 3)]

def test_bulk_update_and_defaults_participate_in_priority_order():
    plugins = ordered()
    plugins.update({"low": 10}, new=5)
    plugins.setdefault("other", 7)
    plugins |= {"new": 11}
    assert plugins.items() == [("new", 11), ("low", 10), ("high", 9), ("other", 7)]
    assert plugins.values() == [11, 10, 9, 7]

def test_pop_and_popitem_remove_heap_entries():
    plugins = ordered()
    assert plugins.pop("high") == 9
    assert plugins.items() == [("low", 1)]
    assert plugins.popitem() == ("low", 1)
    assert plugins.items() == []
    assert plugins.pop("absent", None) is None
    with pytest.raises(KeyError):
        plugins.popitem()
