# encoding:utf-8
"""Inbound Discord attachments are bounded like the other channels' media.

``DiscordChannel._download_attachment`` called ``attachment.save`` with no size
check. discord.py reads the whole body into memory before writing it, and
boosted servers / Nitro accounts can upload hundreds of MB, so one message could
exhaust memory or disk. The Slack, DingTalk, Feishu and WeChat channels already
cap inbound media with ``common.media_download``'s limits.
"""
import asyncio
from types import SimpleNamespace

from common.media_download import MAX_FILE_BYTES, MAX_IMAGE_BYTES


class _Attachment:
    def __init__(self, size, content_type="application/octet-stream", filename="data.bin"):
        self.id = 7
        self.filename = filename
        self.content_type = content_type
        self.size = size
        self.saved = []

    async def save(self, path):
        self.saved.append(path)


def _channel():
    from channel.discord import discord_channel as mod

    cls = mod.DiscordChannel.__wrapped__
    return cls.__new__(cls)


def _parse(attachment):
    message = SimpleNamespace(content="", attachments=[attachment])
    return asyncio.run(_channel()._parse_message(message))


def test_oversized_file_is_skipped_without_downloading():
    att = _Attachment(MAX_FILE_BYTES + 1)

    assert _parse(att) == (None, None, "")
    assert att.saved == []


def test_oversized_image_uses_the_image_limit():
    att = _Attachment(MAX_IMAGE_BYTES + 1, content_type="image/png", filename="big.png")

    assert _parse(att) == (None, None, "")
    assert att.saved == []


def test_attachment_within_the_limit_is_still_downloaded():
    att = _Attachment(1024)

    ctype, path, caption = _parse(att)

    assert path and len(att.saved) == 1
    assert caption == ""
