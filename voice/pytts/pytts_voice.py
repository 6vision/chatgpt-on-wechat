"""
pytts voice service (offline)
"""

import os
import sys
import time

import pyttsx3

from bridge.reply import Reply, ReplyType
from common.log import logger
from common.tmp_dir import TmpDir
from voice.voice import Voice

# espeak drives its own coroutine and has been observed never to report itself
# idle, so the hand-rolled wait below needs an upper bound. Without one a single
# turn blocks the voice thread forever.
_SYNTHESIS_TIMEOUT_S = 30.0
_SYNTHESIS_POLL_S = 0.1


class PyttsVoice(Voice):
    engine = pyttsx3.init()

    def __init__(self):
        # 语速
        self.engine.setProperty("rate", 125)
        # 音量
        self.engine.setProperty("volume", 1.0)
        if sys.platform == "win32":
            for voice in self.engine.getProperty("voices"):
                if "Chinese" in voice.name:
                    self.engine.setProperty("voice", voice.id)
        else:
            self.engine.setProperty("voice", "zh")
            # If the problem of espeak is fixed, using runAndWait() and remove this startLoop()
            # TODO: check if this is work on win32
            self.engine.startLoop(useDriverLoop=False)

    def textToVoice(self, text):
        try:
            # Avoid the same filename under multithreading
            wavFileName = "reply-" + str(int(time.time())) + "-" + str(hash(text) & 0x7FFFFFFF) + ".wav"
            wavFile = TmpDir().path() + wavFileName
            logger.info("[Pytts] textToVoice text={} voice file name={}".format(text, wavFile))

            self.engine.save_to_file(text, wavFile)

            if sys.platform == "win32":
                self.engine.runAndWait()
            else:
                # In ubuntu, runAndWait do not really wait until the file created.
                # It will return once the task queue is empty, but the task is still running in coroutine.
                # And if you call runAndWait() and time.sleep() twice, it will stuck, so do not use this.
                # If you want to fix this, add self._proxy.setBusy(True) in line 127 in espeak.py, at the beginning of the function save_to_file.
                # self.engine.runAndWait()

                # Before espeak fix this problem, we iterate the generator and control the waiting by ourself.
                # But this is not the canonical way to use it, for example if the file already exists it also cannot wait.
                # So bound the wait: a coroutine that never reports idle must not
                # hold the voice thread forever. Checking os.path.exists is
                # equivalent to the previous listdir membership test, without
                # rescanning the whole directory on every poll.
                deadline = time.monotonic() + _SYNTHESIS_TIMEOUT_S
                self.engine.iterate()
                while self.engine.isBusy() or not os.path.exists(wavFile):
                    if time.monotonic() >= deadline:
                        logger.error(
                            "[Pytts] textToVoice timed out after {0}s waiting for {1}",
                            _SYNTHESIS_TIMEOUT_S, wavFileName,
                        )
                        return Reply(
                            ReplyType.ERROR, "抱歉，语音合成超时了，请稍后再试吧~"
                        )
                    time.sleep(_SYNTHESIS_POLL_S)

            return Reply(ReplyType.VOICE, wavFile)

        except Exception as e:
            return Reply(ReplyType.ERROR, str(e))
