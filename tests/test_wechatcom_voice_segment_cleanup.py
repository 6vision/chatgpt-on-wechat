# encoding:utf-8
"""A WeCom-app voice reply must not leave its audio segments in the workspace.

``send`` converts the reply to ``.amr``, calls ``split_audio(amr_file, 60_000)``
and uploads each returned segment. It then deleted only the source file and the
converted ``.amr``:

    os.remove(file_path)
    if amr_file != file_path:
        os.remove(amr_file)

The per-segment files ``split_audio`` exported beside the ``.amr``
(``<stem>_1.amr``, ``<stem>_2.amr``, ...) were never removed, even though every
one of them had just been uploaded and is never read again. They are written
into the Agent's managed ``tmp/`` directory, and nothing in the repository
prunes it: the only age-based sweepers cover the WebChannel's own
``voice_input_*`` uploads and the skills staging area under the OS temp dir.

So every voice reply longer than 60s permanently leaves one orphan file per
minute of audio in the workspace, growing without bound and never reclaimed.
The sibling ``.amr`` and source files were deliberately deleted on the same
path, so the omission is not intentional buffering.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bridge.context import Context
from bridge.reply import Reply, ReplyType
from channel.wechatcom import wechatcomapp_channel as channel_module


class _Recorder:
    """Stands in for ``client.media`` / ``client.message``, recording calls."""

    def __init__(self):
        self.calls = []
        self.media = self
        self.message = self
        self._next = 0

    def upload(self, media_type, media_file):
        if hasattr(media_file, "close"):
            media_file.close()
        self._next += 1
        self.calls.append(("upload", media_type))
        return {"media_id": "media-%d" % self._next}

    def send_voice(self, agent_id, receiver, media_id):
        self.calls.append(("voice", media_id))


def _write(path, body=b"audio"):
    with open(path, "wb") as handle:
        handle.write(body)
    return path


class WechatComVoiceSegmentCleanupTest(unittest.TestCase):
    """Segments produced for a long voice reply must not outlive the send."""

    def setUp(self):
        cls = channel_module.WechatComAppChannel.__wrapped__
        self.channel = cls.__new__(cls)
        self.rec = _Recorder()
        self.channel.agent_id = "1000002"
        self.channel.client = self.rec
        self.context = Context()
        self.context["receiver"] = "user-1"
        self.workdir = tempfile.mkdtemp(prefix="wechatcom-voice-")
        self.source = _write(os.path.join(self.workdir, "reply.wav"))

    def _fake_any_to_amr(self, file_path, amr_file):
        return _write(amr_file)

    def _split_into(self, count):
        """Patch split_audio so it exports *count* segments and return their paths."""
        amr_file = os.path.splitext(self.source)[0] + ".amr"
        stem = amr_file[: amr_file.rindex(".")]
        segments = [_write(os.path.join(self.workdir, "%s_%d.amr" % (stem, i + 1)))
                    for i in range(count)]
        return segments

    def _send_voice_reply(self, segments):
        with patch.object(channel_module, "any_to_amr", self._fake_any_to_amr), \
                patch.object(channel_module, "split_audio",
                             return_value=(len(segments) * 60_000, segments)), \
                patch.object(channel_module.time, "sleep"):
            self.channel.send(Reply(ReplyType.VOICE, self.source), self.context)

    def test_long_voice_leaves_no_orphan_segments(self):
        segments = self._split_into(3)

        self._send_voice_reply(segments)

        for path in segments:
            self.assertFalse(
                os.path.exists(path),
                "%s was uploaded and never read again, so it must not be left "
                "behind in the workspace tmp/" % os.path.basename(path),
            )

    def test_long_voice_still_uploads_and_delivers_every_segment(self):
        """Cleanup must not cost the user the audio itself."""
        segments = self._split_into(3)

        self._send_voice_reply(segments)

        self.assertEqual(3, len([c for c in self.rec.calls if c[0] == "upload"]))
        self.assertEqual(
            ["media-1", "media-2", "media-3"],
            [c[1] for c in self.rec.calls if c[0] == "voice"],
            "every uploaded segment must still be sent to the user",
        )

    def test_the_source_and_converted_amr_are_still_removed(self):
        """The cleanup that already worked must keep working."""
        segments = self._split_into(2)
        amr_file = os.path.splitext(self.source)[0] + ".amr"

        self._send_voice_reply(segments)

        self.assertFalse(os.path.exists(self.source))
        self.assertFalse(os.path.exists(amr_file))

    def test_short_voice_where_split_returns_the_amr_itself_still_delivers(self):
        """split_audio returns [file_path] when the audio fits in one slice.

        That path is the .amr already deleted above, so the new cleanup must not
        trip over removing it twice.
        """
        amr_file = os.path.splitext(self.source)[0] + ".amr"

        with patch.object(channel_module, "any_to_amr", self._fake_any_to_amr), \
                patch.object(channel_module, "split_audio",
                             return_value=(5_000, [amr_file])), \
                patch.object(channel_module.time, "sleep"):
            self.channel.send(Reply(ReplyType.VOICE, self.source), self.context)

        self.assertEqual(1, len([c for c in self.rec.calls if c[0] == "upload"]))
        self.assertEqual(1, len([c for c in self.rec.calls if c[0] == "voice"]))
        self.assertFalse(os.path.exists(self.source))
        self.assertFalse(os.path.exists(amr_file))

    def test_no_audio_file_is_left_behind_at_all(self):
        segments = self._split_into(4)

        self._send_voice_reply(segments)

        leftovers = sorted(os.listdir(self.workdir))
        self.assertEqual([], leftovers)


if __name__ == "__main__":
    unittest.main()
