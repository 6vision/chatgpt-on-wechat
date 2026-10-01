"""Manually followed redirect responses are owned by safe_get."""

from unittest.mock import Mock

import pytest

from agent.tools.utils import url_safety


def _response(location=None):
    response = Mock()
    response.is_redirect = location is not None
    response.is_permanent_redirect = False
    response.headers = {"Location": location} if location else {}
    return response


@pytest.mark.parametrize("error", [ValueError("blocked target"), RuntimeError("resolver failed")])
def test_rejected_redirect_response_is_closed(monkeypatch, error):
    response = _response("https://redirect.example/next")
    request = Mock(return_value=response)
    monkeypatch.setattr(url_safety.requests, "get", request)
    monkeypatch.setattr(url_safety, "validate_url_safe", Mock(side_effect=error))

    with pytest.raises(type(error), match=str(error)):
        url_safety.safe_get("https://source.example/", stream=True)

    response.close.assert_called_once_with()
    request.assert_called_once()


def test_followed_response_is_closed_and_final_response_is_returned(monkeypatch):
    redirect, final = _response("/next"), _response()
    request = Mock(side_effect=[redirect, final])
    validate = Mock()
    monkeypatch.setattr(url_safety.requests, "get", request)
    monkeypatch.setattr(url_safety, "validate_url_safe", validate)

    assert url_safety.safe_get("https://source.example/") is final
    redirect.close.assert_called_once_with()
    final.close.assert_not_called()
    validate.assert_called_once_with("https://source.example/next")


def test_redirect_limit_closes_every_response(monkeypatch):
    responses = [_response("/one"), _response("/two")]
    monkeypatch.setattr(url_safety.requests, "get", Mock(side_effect=responses))
    monkeypatch.setattr(url_safety, "validate_url_safe", Mock())
    with pytest.raises(ValueError, match="Too many redirects"):
        url_safety.safe_get("https://source.example/", max_redirects=1)
    for response in responses:
        response.close.assert_called_once_with()
