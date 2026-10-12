"""Pure JSON configuration merge semantics shared by the app and CLI."""


def deep_merge_dicts(base: dict, incoming: dict) -> dict:
    """Recursively merge ``incoming`` into ``base`` (incoming wins on leaves)."""
    for key, val in incoming.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            deep_merge_dicts(base[key], val)
        else:
            base[key] = val
    return base


def merge_duplicate_keys(pairs, on_duplicates=None):
    """Merge repeated JSON keys; optionally report the repeated key names."""
    out = {}
    duplicates = []
    for key, val in pairs:
        if key not in out:
            out[key] = val
            continue
        duplicates.append(key)
        prev = out[key]
        if isinstance(prev, dict) and isinstance(val, dict):
            deep_merge_dicts(prev, val)
        elif isinstance(prev, list) and isinstance(val, list):
            prev.extend(val)
        else:
            out[key] = val
    if duplicates and on_duplicates is not None:
        on_duplicates(sorted(set(duplicates)))
    return out
