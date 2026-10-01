"""The extension cut out of a sender's document name must not drop the message.

``_parse_message`` derives the document extension from the raw server string
(``"." + doc.file_name.rsplit(".", 1)[-1]``) and ``_download_file`` reduced only
the *name* through ``safe_filename``. When that reducer returns ``""`` — it does
for a name ending in a separator, e.g. ``a./x/`` — the fallback spliced the
*unsanitised* suffix into the path, so ``tmp_dir()/<file_id>./x/`` pointed at a
parent directory that does not exist. python-telegram-bot's plain
``open(custom_path, "wb")`` raised, the bare ``except Exception`` swallowed it,
and ``_parse_message`` returned ``(None, None, "")``: the user's document was
silently discarded with one log line.

The existing ``test_telegram_inbound_document_filename`` covers the empty-name
fallback with a hand-written safe suffix (``.mp4``/``.pdf``), which is why this
input went unpinned.
"""

import asyncio
from pathlib import Path

import pytest

from channel.telegram import telegram_channel as tc

# Names a sender can put in the Bot API's ``filename`` field whose extension
# carries a separator, and the suffix that derivation produces for them.
HOSTILE_NAMES = ["a./x/", "a./", "a.\\x\\", "a./../y"]

# The same hazard reaching ``_download_file`` as a suffix, for the routes that
# build one without a name (photo/audio/video) and for direct callers.
HOSTILE_SUFFIXES = ["./x/", "./", ".\\x\\", "./../y"]

FILE_ID = "BAACAgUAAxkBDDk"


class _FakeFile:
    def __init__(self, written):
        self._written = written

    async def download_to_drive(self, custom_path):
        # What python-telegram-bot does: a plain open() with no mkdir, so a
        # parent directory the name dragged in raises FileNotFoundError here.
        with open(custom_path, "wb") as f:
            f.write(b"payload")
        self._written.append(custom_path)


class _FakeBot:
    def __init__(self, written):
        self._written = written

    async def get_file(self, file_id):
        return _FakeFile(self._written)


def _channel(tmp_path, monkeypatch):
    channel = object.__new__(tc.TelegramChannel.__wrapped__)
    written = []
    channel._bot = _FakeBot(written)
    monkeypatch.setattr(tc.TelegramMessage, "get_tmp_dir", staticmethod(lambda: str(tmp_path)))
    return channel, written


class _FakeDocument:
    def __init__(self, file_name, mime_type="application/octet-stream"):
        self.file_id = FILE_ID
        self.file_name = file_name
        self.mime_type = mime_type


class _FakeMessage:
    """A document-only inbound message: every other branch of _parse_message is falsy."""

    def __init__(self, file_name, mime_type="application/octet-stream", caption=""):
        self.caption = caption
        self.photo = None
        self.voice = None
        self.audio = None
        self.video = None
        self.video_note = None
        self.text = None
        self.document = _FakeDocument(file_name, mime_type)


def _parse(channel, message):
    return asyncio.run(channel._parse_message(message))


# ---------------------------------------------------------------------------
# The regression: a hostile suffix must not become a swallowed download error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hostile", HOSTILE_SUFFIXES)
def test_a_suffix_carrying_a_separator_still_downloads(tmp_path, monkeypatch, hostile):
    channel, written = _channel(tmp_path, monkeypatch)

    path = asyncio.run(channel._download_file(FILE_ID, suffix=hostile, original_name=""))

    assert written, "the download must still run"
    assert path is not None, f"the message must not be dropped by suffix={hostile!r}"
    assert Path(path).parent == tmp_path, f"{path} left the tmp dir"
    assert Path(path).read_bytes() == b"payload"


@pytest.mark.parametrize("hostile", HOSTILE_NAMES)
def test_a_document_whose_name_reduces_to_nothing_is_still_delivered(tmp_path, monkeypatch, hostile):
    """End to end through _parse_message: the real user-visible outcome."""
    channel, written = _channel(tmp_path, monkeypatch)

    ctype, path, _caption = _parse(channel, _FakeMessage(hostile, caption="my file"))

    assert path is not None, f"file_name={hostile!r} silently dropped the document"
    assert ctype is tc.ContextType.FILE
    assert written, "the download must still run"
    assert Path(path).parent == tmp_path, f"{path} left the tmp dir"
    assert Path(path).read_bytes() == b"payload"


def test_a_hostile_suffix_loses_the_separator_instead_of_joining_a_directory(tmp_path, monkeypatch):
    """Pin the exact fallback: bare file_id, no separator and no dangling dot."""
    channel, _ = _channel(tmp_path, monkeypatch)

    path = asyncio.run(
        channel._download_file(FILE_ID, suffix="./x/", original_name="a./x/")
    )

    assert Path(path).name == FILE_ID
    assert Path(path).is_file()


# ---------------------------------------------------------------------------
# Guards: the normal cases must behave exactly as before
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("suffix,expected", [(".mp4", f"{FILE_ID}.mp4"),
                                            (".pdf", f"{FILE_ID}.pdf"),
                                            (".tar.gz", f"{FILE_ID}.tar.gz")])
def test_a_known_safe_suffix_still_becomes_the_extension(suffix, expected, tmp_path, monkeypatch):
    channel, _ = _channel(tmp_path, monkeypatch)

    path = asyncio.run(channel._download_file(FILE_ID, suffix=suffix, original_name=""))

    assert Path(path).name == expected
    assert Path(path).read_bytes() == b"payload"


def test_a_normal_document_name_still_keeps_its_extension(tmp_path, monkeypatch):
    channel, _ = _channel(tmp_path, monkeypatch)

    ctype, path, caption = _parse(channel, _FakeMessage("quarterly report.pdf", caption="q1"))

    assert ctype is tc.ContextType.FILE
    assert Path(path).name == f"{FILE_ID}_quarterly report.pdf"
    assert Path(path).parent == tmp_path
    assert caption == "q1"
    assert Path(path).read_bytes() == b"payload"


def test_a_normal_document_name_still_keeps_a_name_without_an_extension(tmp_path, monkeypatch):
    channel, _ = _channel(tmp_path, monkeypatch)

    _ctype, path, _caption = _parse(channel, _FakeMessage("README"))

    assert Path(path).name == f"{FILE_ID}_README"


def test_an_image_document_is_still_typed_as_an_image(tmp_path, monkeypatch):
    channel, _ = _channel(tmp_path, monkeypatch)

    ctype, path, _caption = _parse(channel, _FakeMessage("shot.png", mime_type="image/png"))

    assert ctype is tc.ContextType.IMAGE
    assert Path(path).name == f"{FILE_ID}_shot.png"
