import json
import sqlite3
import struct
import pytest
from agent.memory import vector_backend

@pytest.mark.parametrize("numpy_enabled", [False, True])
@pytest.mark.parametrize("damaged", [b"x", "invalid JSON", '["invalid", 1]', struct.pack("2f", float("nan"), 1.0), json.dumps([10 ** 400, 1])])
def test_one_damaged_row_cannot_hide_a_healthy_match(monkeypatch, numpy_enabled, damaged):
    if numpy_enabled and vector_backend.np is None:
        pytest.skip("NumPy is optional")
    monkeypatch.setattr(vector_backend, "_HAS_NUMPY", numpy_enabled)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE chunks (id TEXT, embedding BLOB, user_id TEXT, scope TEXT, source TEXT, path TEXT, start_line INTEGER, end_line INTEGER, text TEXT, metadata TEXT)")
    backend = vector_backend.SQLiteVectorBackend(conn)
    for identifier, embedding in [("broken", damaged), ("healthy", backend._encode_embedding([1.0, 0.0]))]:
        conn.execute("INSERT INTO chunks VALUES (?, ?, NULL, 'shared', 'memory', ?, 1, 1, ?, NULL)", (identifier, embedding, identifier + ".md", identifier))
    try:
        matches = backend.search([1.0, 0.0], limit=1)
        assert [match.id for match in matches] == ["healthy"]
        assert matches[0].score == pytest.approx(1.0)
    finally:
        conn.close()
