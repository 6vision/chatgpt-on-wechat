"""An image WeCom cannot take is reported as a failure, not passed through."""

import pytest

from channel.wecom_bot import wecom_bot_channel as mod

_ensure_image_format = mod.WecomBotChannel.__wrapped__._ensure_image_format

PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d4944415478da63f8cfc0000003010100"
    "18dd8db00000000049454e44ae426082"
)


def test_supported_image_is_unchanged(tmp_path):
    path = tmp_path / "ok.png"
    path.write_bytes(PNG_BYTES)
    assert _ensure_image_format(str(path)) == str(path)


@pytest.mark.parametrize("name, payload", [
    ("broken.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 not-a-real-image-body"),
    ("x.heic", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 68),
    ("absent.png", None),
])
def test_unconvertible_image_returns_empty(tmp_path, name, payload):
    path = tmp_path / name
    if payload is not None:
        path.write_bytes(payload)
    assert _ensure_image_format(str(path)) == ""
