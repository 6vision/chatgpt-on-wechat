"""What the xunfei voice writes to the console while it is being constructed.

``XunfeiVoice.__init__`` reads ``voice/xunfei/config.json`` -- APPID, APIKey and
APISecret in cleartext -- and it did so with a bare ``print(conf)``. That put the
whole credential dict on stdout: not through ``logger``, so not through the
``drag_sensitive`` masking config.py applies to every other credential line.
``bridge`` builds a voice the first time a type is used and again on every
``Bridge.reset_bot()`` (config saves, ``$linkai open|close``), so the dump
repeated across a session and landed in the console, in ``nohup.out`` and in any
redirected or shared log file.

Construction itself is offline -- the file is read, the five values are copied
onto the instance, no socket is opened -- so the test drives the real thing. The
config is written into ``tmp_path`` and the module's ``__file__`` is pointed at
it, so no real config.json is ever read or written.
"""

import json
import logging
import os

from voice.xunfei import xunfei_voice as xv
from voice.xunfei.xunfei_voice import XunfeiVoice

APPID = "sentinel-appid-0001"
API_KEY = "sentinel-apikey-0002"
API_SECRET = "sentinel-apisecret-0003"

BUSINESS_ARGS_TTS = {"aue": "lame", "sfl": 1, "auf": "audio/L16;rate=16000",
                     "vcn": "xiaoyan", "tte": "utf8"}
BUSINESS_ARGS_ASR = {"domain": "iat", "language": "zh_cn", "accent": "mandarin",
                     "vad_eos": 10000, "dwa": "wpgs"}


def _point_at_a_temp_config(tmp_path, monkeypatch):
    """Give the module a config.json of its own, in the test's temp directory.

    ``__init__`` resolves the config as ``dirname(__file__) + "config.json"``, so
    repointing ``__file__`` is what keeps the test off the checked-out file.
    """
    (tmp_path / "config.json").write_text(json.dumps({
        "APPID": APPID,
        "APIKey": API_KEY,
        "APISecret": API_SECRET,
        "BusinessArgsTTS": BUSINESS_ARGS_TTS,
        "BusinessArgsASR": BUSINESS_ARGS_ASR,
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(xv, "__file__", os.path.join(str(tmp_path), "xunfei_voice.py"))


class _Collector(logging.Handler):
    """Gather what a logger was handed, whatever its own handlers do with it.

    ``common.log`` holds a reference to the stdout it saw at import time and sets
    ``propagate = False``, so reading the test's own stdout is not enough to see
    whether the secrets were routed to the logger instead of ``print``ed.
    """

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def test_building_the_voice_keeps_the_credentials_off_stdout(tmp_path, monkeypatch, capsys):
    _point_at_a_temp_config(tmp_path, monkeypatch)

    XunfeiVoice()
    out = capsys.readouterr().out

    assert API_KEY not in out, "the xunfei APIKey was printed to stdout"
    assert API_SECRET not in out, "the xunfei APISecret was printed to stdout"
    assert APPID not in out, "the xunfei APPID was printed to stdout"
    assert "sentinel" not in out, "the credentials were dumped as a whole"


def test_building_the_voice_keeps_the_credentials_out_of_the_log(tmp_path, monkeypatch):
    _point_at_a_temp_config(tmp_path, monkeypatch)
    collector = _Collector()
    log = logging.getLogger("log")
    log.addHandler(collector)
    try:
        XunfeiVoice()
    finally:
        log.removeHandler(collector)

    logged = "\n".join(collector.messages)
    assert API_KEY not in logged, "the xunfei APIKey reached the log"
    assert API_SECRET not in logged, "the xunfei APISecret reached the log"
    assert APPID not in logged, "the xunfei APPID reached the log"
    assert "sentinel" not in logged, "the credentials were logged as a whole"


def test_the_credentials_are_still_read_from_the_config(tmp_path, monkeypatch):
    """The point of the dump was never the point: everything else must survive."""
    _point_at_a_temp_config(tmp_path, monkeypatch)

    voice = XunfeiVoice()

    assert voice.APPID == APPID
    assert voice.APIKey == API_KEY
    assert voice.APISecret == API_SECRET
    assert voice.BusinessArgsTTS == BUSINESS_ARGS_TTS
    assert voice.BusinessArgsASR == BUSINESS_ARGS_ASR
