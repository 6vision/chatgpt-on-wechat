# encoding:utf-8
"""Whether the Aliyun NLS token is fetched over a channel anybody can read.

``AliyunTokenGenerator.get_token`` built its metadata URL as
``http://nls-meta.cn-shanghai.aliyuncs.com/?...`` and fetched it with
``requests.get``. Plain HTTP means the entire request line is on the wire in the
clear, and that request line is the credential: it carries ``AccessKeyId`` next to
the HMAC-SHA1 ``Signature`` computed over a ``Timestamp`` and ``SignatureNonce``
the caller itself chose.

That signature does not need to be cracked, only copied. Replaying the exact same
signed request returns the ``Token`` object -- an ``Id`` and an ``ExpireTime`` --
and that token is the ``X-NLS-Token`` header on every subsequent ASR and TTS
call. So a single passive read on any network path between the host and Aliyun
-- a hostile hotspot, a corporate router, any upstream that logs request lines --
hands over live voice access to the account, for as long as the token lasts, with
no key material ever being broken.

The fix is the scheme. Everything else about the request is already correct and is
untouched: the host, the signed parameters, the timeout, and the response body
handed back to the caller. Note that the same module already speaks TLS properly
for recognition -- ``speech_to_text_aliyun`` opens an ``http.client.HTTPSConnection``
-- so this call was the outlier rather than the rule.

No network call is made: the ``requests`` module is replaced by a recorder.
"""
import os
import sys
import unittest
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from voice.ali import ali_api

ACCESS_KEY_ID = "sentinel-ak-0001"
ACCESS_KEY_SECRET = "sentinel-sk-0002"

TOKEN_BODY = '{"Token":{"Id":"sentinel-token-0003","ExpireTime":4102444800}}'


class _FakeResponse(object):
    """The parts of a ``requests`` response that ``get_token`` reads."""

    text = TOKEN_BODY


class _RecordingRequests(object):
    """Stands in for the ``requests`` module and records the call it is given."""

    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _FakeResponse()

    @property
    def url(self):
        self.assert_one_call()
        return self.calls[0][0]

    def kwargs(self):
        self.assert_one_call()
        return self.calls[0][1]

    def assert_one_call(self):
        assert len(self.calls) == 1, "expected exactly one request, got %d" % len(self.calls)


class AliyunTokenHttpsTest(unittest.TestCase):
    def setUp(self):
        self.recorder = _RecordingRequests()
        self.real = ali_api.requests
        ali_api.requests = self.recorder
        self.generator = ali_api.AliyunTokenGenerator(ACCESS_KEY_ID, ACCESS_KEY_SECRET)
        self.body = self.generator.get_token()

    def tearDown(self):
        ali_api.requests = self.real

    def test_the_token_is_fetched_over_https(self):
        """The defect: a signed credential sent where anyone can read it."""
        url = self.recorder.url
        parts = urllib.parse.urlsplit(url)
        self.assertEqual(
            parts.scheme,
            "https",
            "the token request is plaintext, so AccessKeyId and Signature are "
            "readable and replayable by anything on the path: %r" % (url,),
        )
        self.assertEqual(parts.hostname, "nls-meta.cn-shanghai.aliyuncs.com")
        self.assertEqual(parts.path, "/")

    def test_the_signed_parameters_are_unchanged(self):
        """Secure scheme only -- the request itself must still be the same one."""
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.recorder.url).query)
        self.assertEqual(params["AccessKeyId"], [ACCESS_KEY_ID])
        self.assertEqual(params["Action"], ["CreateToken"])
        self.assertEqual(params["RegionId"], ["cn-shanghai"])
        self.assertEqual(params["Version"], ["2019-02-28"])
        self.assertEqual(params["SignatureMethod"], ["HMAC-SHA1"])
        self.assertTrue(params["Signature"][0], "the request went out unsigned")
        # The nonce and timestamp are what the signature covers, so they have to
        # still be present for Aliyun to accept the replay-free claim.
        self.assertTrue(params["SignatureNonce"][0])
        self.assertTrue(params["Timestamp"][0])
        # And the read bounds are untouched.
        self.assertEqual(self.recorder.kwargs().get("timeout"), (5, 60))

    def test_certificate_verification_is_left_on(self):
        """HTTPS is only as good as the check behind it."""
        verify = self.recorder.kwargs().get("verify", True)
        self.assertNotEqual(
            verify,
            False,
            "certificate verification was switched off on the token request",
        )

    def test_the_token_body_is_returned(self):
        self.assertEqual(self.body, TOKEN_BODY)

    def test_recognition_already_speaks_tls(self):
        """Why this was an outlier: the ASR path in the same module uses HTTPS."""
        source = open(ali_api.__file__, encoding="utf-8").read()
        self.assertIn("http.client.HTTPSConnection", source)
        self.assertNotIn(
            "http://nls-",
            source,
            "a plaintext aliyun voice endpoint is left in the module",
        )


if __name__ == "__main__":
    unittest.main()
