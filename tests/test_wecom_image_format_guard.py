"""An image that cannot be converted must not be sent on as if it had been.

``_ensure_image_format`` promises "Ensure image is JPG or PNG (the only formats
wecom supports). Convert if needed" -- and its except path returned the
*original* path, which is the one value that promise rules out. Both callers
guard on an empty return:

    callback  :991   if not formatted: return None
    websocket :1136  if not local_path:
                          self._send_text("[Image format conversion failed]", ...)

so neither guard could fire, and the failure notice the author wrote for the
websocket path was unreachable. An image PIL cannot open -- a truncated
download, a corrupt or exotic format -- was uploaded or base64'd into the
callback packet unchanged, and WeCom rejects it platform-side: the image never
appears and nothing says why.

Measured with the real helper:

    a real PNG                        -> returned unchanged  (correct)
    a truncated .webp                 -> returned unchanged  (the bug)
    an undecodable .heic              -> returned unchanged  (the bug)
    guard `if not formatted: ...`     -> never taken
"""

import os
import sys
import tempfile
import unittest

ROOT = "/".join(__file__.replace("\\", "/").split("/")[:-2])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from channel.wecom_bot import wecom_bot_channel as mod  # noqa: E402

# @singleton rebinds the name to get_instance(); the class is on __wrapped__.
_ensure_image_format = mod.WecomBotChannel.__wrapped__._ensure_image_format

# A 1x1 PNG, byte-for-byte, so the control needs no Pillow round-trip.
PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d4944415478da63f8cfc0000003010100"
    "18dd8db00000000049454e44ae426082"
)


def _write(directory, name, payload):
    path = os.path.join(directory, name)
    with open(path, "wb") as handle:
        handle.write(payload)
    return path


class EnsureImageFormatTest(unittest.TestCase):
    """The contract is "JPG or PNG, or nothing"."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wecom-format-")

    def test_a_supported_image_is_returned_unchanged(self):
        path = _write(self.tmp, "ok.png", PNG_BYTES)
        self.assertEqual(_ensure_image_format(path), path)

    def test_an_image_pillow_cannot_open_reports_failure(self):
        # A truncated WebP: the header parses, the body does not.
        path = _write(self.tmp, "broken.webp",
                      b"RIFF\x00\x00\x00\x00WEBPVP8 not-a-real-image-body")
        self.assertEqual(
            _ensure_image_format(path), "",
            "an unconvertible image was handed back as if it were ready to send",
        )

    def test_an_undecodable_format_reports_failure(self):
        path = _write(self.tmp, "x.heic",
                      b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00" + b"\x00" * 64)
        self.assertEqual(_ensure_image_format(path), "")

    def test_the_callers_guards_can_now_fire(self):
        # The point of returning "": both call sites already branch on it, and
        # the websocket one has a user-facing notice that was unreachable.
        import inspect

        source = inspect.getsource(mod)
        self.assertIn("if not formatted:", source,
                      "the callback path's guard disappeared")
        self.assertIn("[Image format conversion failed]", source,
                      "the websocket path's failure notice disappeared")

    def test_a_missing_file_reports_failure(self):
        self.assertEqual(
            _ensure_image_format(os.path.join(self.tmp, "absent.png")), "")


if __name__ == "__main__":
    unittest.main()