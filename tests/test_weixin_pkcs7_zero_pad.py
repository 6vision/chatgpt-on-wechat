# encoding:utf-8
"""Weixin PKCS#7 unpadding must not swallow a body whose last byte is 0x00.

``_aes_ecb_decrypt`` guarded only the upper bound of the padding length::

    pad_len = decrypted[-1]
    if pad_len > 16:
        return decrypted
    return decrypted[:-pad_len]

``pad_len == 0`` falls straight into that slice, and ``data[:-0]`` is the
*empty* sequence rather than the whole buffer, so every plaintext byte is
discarded.

A CDN body that is not PKCS#7 padded -- or one decrypted with a key that only
matches up to the final block -- ends in ``0x00``, and the download then saved a
0-byte file and returned its path as a success. The channel then handed the user
an empty/corrupt attachment instead of the bytes it actually received.

``0`` cannot be a PKCS#7 pad length (the encoding always emits 1..16), so it is
the one value that unambiguously means "no padding to strip".
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Crypto.Cipher import AES

from channel.weixin import weixin_api

KEY = bytes(range(16))

# A full, unpadded 16-byte block whose final byte happens to be 0x00.
RAW_BLOCK = b"media-bytes-abc\x00"


def _encrypt_raw(block, key=KEY):
    """Encrypt *block* verbatim, i.e. produce a body with no PKCS#7 padding."""
    return AES.new(key, AES.MODE_ECB).encrypt(block)


def _encrypt_padded(payload, key=KEY):
    """PKCS#7-pad and encrypt, mirroring what a well-behaved CDN sends."""
    pad = 16 - len(payload) % 16
    return AES.new(key, AES.MODE_ECB).encrypt(payload + bytes([pad]) * pad)


class _StreamingResponse:
    """A CDN download that only offers the streaming API."""

    def __init__(self, chunks, headers=None):
        self._chunks = chunks
        self.headers = headers or {}
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=8192):
        yield from self._chunks

    def close(self):
        self.closed = True


class _CdnSession:
    def __init__(self, response):
        self._response = response

    def get(self, *args, **kwargs):
        return self._response


class WeixinPkcs7ZeroPadTest(unittest.TestCase):
    """A trailing 0x00 must not be mistaken for a padding length."""

    def test_zero_trailing_byte_returns_the_plaintext(self):
        decrypted = weixin_api._aes_ecb_decrypt(_encrypt_raw(RAW_BLOCK), KEY)

        self.assertEqual(
            RAW_BLOCK, decrypted,
            "data[:-0] is empty, so a body ending in 0x00 was reduced to nothing",
        )

    def test_a_saved_media_file_is_not_empty(self):
        """The user-visible end of the bug: a 0-byte attachment saved as success."""
        workdir = tempfile.mkdtemp(prefix="weixin-pkcs7-")
        save_path = os.path.join(workdir, "media.bin")
        response = _StreamingResponse([_encrypt_raw(RAW_BLOCK)])

        with patch.object(weixin_api, "_get_cdn_session", lambda: _CdnSession(response)):
            returned = weixin_api.download_media_from_cdn(
                "https://cdn.example.com", "encrypted-param", KEY.hex(), save_path,
            )

        with open(returned, "rb") as handle:
            written = handle.read()
        self.assertEqual(RAW_BLOCK, written)
        self.assertTrue(os.path.getsize(returned) > 0, "a 0-byte download is corrupt")

    def test_ordinary_pkcs7_padding_is_still_stripped(self):
        self.assertEqual(b"payload", weixin_api._aes_ecb_decrypt(_encrypt_padded(b"payload"), KEY))

    def test_a_full_length_padding_block_still_empties_correctly(self):
        """pad_len == 16 is real padding and must still strip the whole block."""
        encrypted = _encrypt_padded(b"0123456789abcde")

        self.assertEqual(b"0123456789abcde", weixin_api._aes_ecb_decrypt(encrypted, KEY))

    def test_an_implausible_pad_length_still_returns_the_raw_bytes(self):
        """The pre-existing lenient path for pad_len > 16 must be unchanged."""
        block = b"0123456789abcde\xff"

        self.assertEqual(block, weixin_api._aes_ecb_decrypt(_encrypt_raw(block), KEY))


if __name__ == "__main__":
    unittest.main()
