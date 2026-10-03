# encoding:utf-8
"""The Aliyun NLS token request goes over https."""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from voice.ali import ali_api


def test_token_is_fetched_over_https():
    with patch.object(ali_api, "requests") as requests:
        requests.get.return_value.text = '{"Token":{"Id":"t"}}'
        body = ali_api.AliyunTokenGenerator("ak", "sk").get_token()

    url = requests.get.call_args.args[0]
    assert url.startswith("https://nls-meta.cn-shanghai.aliyuncs.com/?")
    assert "AccessKeyId=ak" in url
    assert body == '{"Token":{"Id":"t"}}'
