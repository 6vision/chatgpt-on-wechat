import threading
import importlib

from agent.tools.edit.edit import Edit


def test_native_concurrent_edits_preserve_both_replacements(tmp_path, monkeypatch):
    target = tmp_path / "notes.md"
    target.write_bytes(b"alpha\nbeta\n")
    ready = threading.Event()
    release = threading.Event()
    second_done = threading.Event()
    module = importlib.import_module("agent.tools.edit.edit")
    original_write = module.write_text_atomic

    def controlled_write(path, content, **kwargs):
        if threading.current_thread().name == "first":
            ready.set()
            assert release.wait(3)
        return original_write(path, content, **kwargs)

    monkeypatch.setattr(module, "write_text_atomic", controlled_write)
    outcomes = []

    def edit(old, new, completed=None):
        result = Edit({"cwd": str(tmp_path)}).execute({"path": "notes.md", "oldText": old, "newText": new})
        outcomes.append(result.status == "success")
        if completed:
            completed.set()

    first = threading.Thread(target=edit, args=("alpha", "ALPHA"), name="first")
    second = threading.Thread(target=edit, args=("beta", "BETA", second_done))
    try:
        first.start()
        assert ready.wait(3)
        second.start()
        # In the old implementation the second edit publishes while the first
        # still holds a stale snapshot. With locking it waits for admission.
        second_done.wait(0.5)
    finally:
        release.set()
        first.join(3)
        if second.ident:
            second.join(3)
    assert not first.is_alive() and not second.is_alive()
    assert outcomes == [True, True]
    assert target.read_bytes() == b"ALPHA\nBETA\n"
