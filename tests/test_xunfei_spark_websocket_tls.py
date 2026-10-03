"""The TLS settings the Xunfei Spark websocket is opened with.

``XunFeiBot.create_web_socket`` opens its ``wss://`` stream with
``sslopt={"cert_reqs": ssl.CERT_NONE}``, which tells websocket-client to accept
any certificate the peer presents. The query string on that connection is the
``authorization`` parameter ``create_url`` signs with the app's APIKey and
APISecret, so an active network attacker can present a certificate of their own,
read the signed credentials off the handshake, and both capture the stream and
impersonate the client.

websocket-client treats an ``sslopt`` ``context`` as authoritative -- it wraps
the socket with it as given -- and only builds a context of its own from
``cert_reqs`` when there is none. So what matters is the ``sslopt`` dict that
reaches ``run_forever``. The test captures it with a fake ``WebSocketApp``:
no socket is opened, and no credentials have to be configured for it to run.
"""

import ssl

from models.xunfei import xunfei_spark_bot as xsb


def _run_forever_sslopt(monkeypatch):
    """Run ``create_web_socket`` against a fake ``WebSocketApp``, and report the
    ``sslopt`` its ``run_forever`` was handed.

    ``create_url`` is stubbed because signing the URL needs configured
    credentials and has no bearing on the TLS options under test.
    """
    captured = {}

    class _FakeWebSocketApp:

        def __init__(self, url, **callbacks):
            captured["url"] = url

        def run_forever(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(xsb.websocket, "WebSocketApp", _FakeWebSocketApp)
    monkeypatch.setattr(xsb.websocket, "enableTrace", lambda *a, **k: None)
    monkeypatch.setattr(
        xsb.XunFeiBot, "create_url",
        lambda self: "wss://spark-api.xf-yun.com/v3.5/chat?authorization=stubbed",
    )

    xsb.XunFeiBot().create_web_socket("hello", "spark-tls-probe")

    assert "sslopt" in captured, (
        "create_web_socket opened the stream without any sslopt at all"
    )
    return captured["sslopt"]


def test_the_stream_is_opened_with_a_certificate_verifying_context(monkeypatch):
    sslopt = _run_forever_sslopt(monkeypatch)

    context = sslopt.get("context")
    assert isinstance(context, ssl.SSLContext), (
        "the stream must be opened with an SSLContext that verifies the server "
        f"certificate, but sslopt was {sslopt!r}"
    )
    assert context.verify_mode == ssl.CERT_REQUIRED, (
        f"the context must require a verified certificate, not {context.verify_mode!r}"
    )
    assert context.check_hostname is True, (
        "a valid certificate for another host must not satisfy the connection"
    )


def test_the_stream_does_not_disable_certificate_verification(monkeypatch):
    sslopt = _run_forever_sslopt(monkeypatch)

    assert sslopt.get("cert_reqs") != ssl.CERT_NONE, (
        "cert_reqs=CERT_NONE accepts whatever certificate the peer presents, "
        "which is what lets an attacker read the signed authorization parameter "
        "and the audio off this connection"
    )