# encoding:utf-8
"""Weixin PKCS#7 unpadding keeps the plaintext when the last decrypted byte is 0x00."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from Crypto.Cipher import AES

from channel.weixin import weixin_api

KEY = bytes(range(16))


@pytest.mark.parametrize("plain,expected", [
    (b"media-bytes-abc\x00", b"media-bytes-abc\x00"),
    (b"payload" + b"\x09" * 9, b"payload"),
])
def test_aes_ecb_decrypt_unpad(plain, expected):
    encrypted = AES.new(KEY, AES.MODE_ECB).encrypt(plain)
    assert weixin_api._aes_ecb_decrypt(encrypted, KEY) == expected
