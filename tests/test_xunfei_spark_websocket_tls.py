"""The Xunfei Spark websocket is opened with a certificate-verifying TLS context."""

import ssl

from models.xunfei import xunfei_spark_bot as xsb


def test_stream_uses_verifying_ssl_context(monkeypatch):
    captured = {}

    class _FakeWebSocketApp:
        def __init__(self, url, **callbacks):
            pass

        def run_forever(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(xsb.websocket, "WebSocketApp", _FakeWebSocketApp)
    monkeypatch.setattr(xsb.websocket, "enableTrace", lambda *a, **k: None)
    monkeypatch.setattr(xsb.XunFeiBot, "create_url", lambda self: "wss://spark.example/chat")

    xsb.XunFeiBot().create_web_socket("hello", "spark-tls-probe")

    context = captured["sslopt"]["context"]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
