# encoding:utf-8
"""
Tests that a remote config push survives an unconfigured LinkAI plugin.

Defect: the dall-e branch of ``CloudClient.on_config`` dereferenced
``pconf("linkai")`` directly, while the midjourney branch immediately above
it guarded the same lookup with ``and pconf("linkai")``. ``pconf`` is a plain
``dict.get``, so a user who has never configured the LinkAI plugin gets
``None`` back and the subscript raised ``TypeError``.

User-visible consequence: the exception escaped ``on_config`` before
``_save_config_to_file`` ran, so every model / voice / channel-credential
edit the same push had already staged in ``local_config`` was silently
dropped - the cloud console reported success and the device changed nothing.
"""

import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# The remote client module imports an optional runtime SDK that is not present
# in the test environment. Stub the few names it binds at import time, the same
# way the other cloud_client tests do.
if "linkai" not in sys.modules:
    _stub = types.ModuleType("linkai")

    class _LinkAIClient:  # minimal base so CloudClient can subclass it
        def __init__(self, *a, **k):
            pass

    class _PushMsg:
        pass

    _stub.LinkAIClient = _LinkAIClient
    _stub.PushMsg = _PushMsg
    sys.modules["linkai"] = _stub

import common.cloud_client as cloud_client  # noqa: E402
from common.cloud_client import CloudClient  # noqa: E402


def make_client():
    """A CloudClient with no websocket, config transport or plugin state.

    ``__new__`` skips ``__init__`` so nothing connects; ``on_config`` only
    reads ``client_id`` and ``_peer_transport`` before reaching the branch
    under test. ``channel_mgr`` stays None so a staged channel change logs
    "restart manually" instead of trying to restart a channel.
    """
    client = CloudClient.__new__(CloudClient)
    client.client_id = "test-client"
    client._peer_transport = None
    client.channel_mgr = None
    return client


class ConfigPushTestBase(unittest.TestCase):
    """A temporary root holding a real config.json, and no LinkAI plugin."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.config_path = os.path.join(self.root, "config.json")
        with open(self.config_path, "w", encoding="utf-8") as handle:
            json.dump({"channel_type": "web"}, handle)

    def stored_config(self):
        """Read config.json back from disk."""
        with open(self.config_path, encoding="utf-8-sig") as handle:
            return json.load(handle)

    def push(self, remote_config, linkai_config):
        """Run on_config against the temp root with ``linkai_config`` in place.

        ``linkai_config`` of None is the unconfigured-plugin case: it is what
        ``pconf`` returns for a plugin that has never been written.
        """
        client = make_client()
        with patch.object(cloud_client, "get_root", return_value=self.root), \
                patch.object(cloud_client, "conf", return_value={}), \
                patch.object(cloud_client, "pconf", return_value=linkai_config):
            client.on_config(remote_config)


class TestDallEPushWithoutLinkAIPlugin(ConfigPushTestBase):
    """The push must complete rather than raise on a missing plugin config."""

    def test_dall_e_push_does_not_raise(self):
        """The reported defect: TypeError out of the config callback."""
        self.push({"enabled": "Y", "text_to_image": "dall-e-3"}, None)

    def test_dall_e_2_push_does_not_raise(self):
        """Both dall-e spellings share the unguarded branch."""
        self.push({"enabled": "Y", "text_to_image": "dall-e-2"}, None)

    def test_configured_model_is_still_saved(self):
        """The staged model edit must reach disk despite the plugin gap."""
        self.push(
            {"enabled": "Y", "text_to_image": "dall-e-3", "model": "gpt-4o"},
            None,
        )
        self.assertEqual(self.stored_config().get("model"), "gpt-4o")

    def test_staged_channel_type_is_still_saved(self):
        """A second staged setting proves the save is not a fluke of one key."""
        self.push(
            {"enabled": "Y", "text_to_image": "dall-e-3", "channelType": "web"},
            None,
        )
        self.assertEqual(self.stored_config().get("channel_type"), "web")


class TestDallEPushWithLinkAIPlugin(ConfigPushTestBase):
    """The guard must not disable the behaviour it was protecting."""

    def test_image_prefix_is_still_turned_off(self):
        """A configured plugin still gets use_image_create_prefix disabled."""
        linkai = {"midjourney": {"enabled": True, "use_image_create_prefix": True}}
        self.push({"enabled": "Y", "text_to_image": "dall-e-3"}, linkai)
        self.assertIs(linkai["midjourney"]["use_image_create_prefix"], False)

    def test_configured_model_is_saved(self):
        """The save path is unchanged when the plugin is present."""
        self.push(
            {"enabled": "Y", "text_to_image": "dall-e-3", "model": "gpt-4o"},
            {"midjourney": {"enabled": True}},
        )
        self.assertEqual(self.stored_config().get("model"), "gpt-4o")


if __name__ == "__main__":
    unittest.main()
