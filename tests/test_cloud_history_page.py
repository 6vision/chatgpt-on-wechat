# encoding:utf-8
"""A bad ``page`` must be reported, not raised out of the history query.

``_query_history`` has a ``try/except`` that turns every failure into a
``{"status": "error"}`` envelope, but the two ``int()`` conversions sat above
it, and above the ``session_id`` check too. A non-numeric ``page`` from the
console therefore raised out of the handler instead of being reported.

Every case here is answered before the query reaches the conversation store, so
the tests stay shallow and offline.
"""

from common.cloud_client import CloudClient


def _query(payload):
    # __new__ skips __init__ so no websocket or cloud connection is opened; the
    # paths under test all return before anything else on the instance is used.
    client = CloudClient.__new__(CloudClient)
    return client._query_history(payload)


def _message(payload):
    result = _query(payload)
    assert result["action"] == "query", result
    assert result["payload"]["status"] == "error", result
    return result["payload"]["message"]


def test_a_non_numeric_page_is_reported():
    assert "integers" in _message({"session_id": "s1", "page": "abc"})


def test_a_null_page_is_reported():
    assert "integers" in _message({"session_id": "s1", "page": None})


def test_a_non_numeric_page_size_is_reported():
    assert "integers" in _message({"session_id": "s1", "page_size": "twenty"})


def test_a_list_page_is_reported():
    assert "integers" in _message({"session_id": "s1", "page": [1]})


def test_a_bad_page_without_a_session_id_still_reports_the_session_id():
    """The session_id check keeps its precedence over the new one."""
    assert "session_id required" in _message({"page": "abc"})


def test_a_numeric_string_page_is_not_treated_as_malformed():
    # "2" is an ordinary thing for a client to send, and int("2") is 2, so the
    # only thing this asserts is that parsing did not raise: reaching the
    # session_id check is the observable proof.
    assert "session_id required" in _message({"page": "2", "page_size": "5"})
