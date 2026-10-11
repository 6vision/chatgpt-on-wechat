"""Inbound files with the same display name get separate save paths."""

from pathlib import Path

import pytest

from channel.weixin import weixin_message as messages


@pytest.fixture(autouse=True)
def tmp_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(messages, "_get_tmp_dir", lambda: str(tmp_path))
    return tmp_path


def _file_msg(name, msg_id="m1"):
    raw = {"message_type": 1, "message_id": msg_id, "from_user_id": "u", "to_user_id": "bot",
           "item_list": [{"type": messages.ITEM_FILE, "file_item": {
               "file_name": name, "media": {"encrypt_query_param": "q", "aes_key": "00" * 16}}}]}
    return messages.WeixinMessage(raw, cdn_base_url="http://cdn.invalid")


def test_same_name_and_same_msg_id_get_separate_paths(tmp_dir):
    first, second = _file_msg("report.txt"), _file_msg("report.txt")
    assert first.content != second.content
    for msg in (first, second):
        assert Path(msg.content).parent == tmp_dir
        assert Path(msg.content).name.endswith("report.txt")
        assert not Path(msg.content).exists()


@pytest.mark.parametrize("name,ending", [
    ("财务报告.txt", "财务报告.txt"), ("reports/report.txt", "report.txt"),
    ("..\\report.txt", "report.txt"), ("", ".bin"),
])
def test_display_name_is_sanitized_and_kept(tmp_dir, name, ending):
    path = Path(_file_msg(name).content)
    assert path.parent == tmp_dir
    assert path.name.endswith(ending)


def test_long_utf8_name_fits_the_filesystem_limit():
    path = Path(_file_msg("财" * 80 + ".txt").content)
    assert len(path.name.encode("utf-8")) <= 255
    assert path.suffix == ".txt"
