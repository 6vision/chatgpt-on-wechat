"""A masked channel credential posted back must never overwrite the real one."""

import pytest

from channel.web.api.channels import ChannelsHandler

SECRET = "ABCDefghijklmnopqrstuvwx"


@pytest.mark.parametrize("length", range(9, 25))
def test_every_mask_is_recognised(length):
    assert ChannelsHandler._is_masked_secret(ChannelsHandler._mask_secret(SECRET[:length]))


@pytest.mark.parametrize("value", [SECRET[:1], SECRET[:8], SECRET[:9], SECRET, "AB*CD*EFGH", "ABCD*EFGH-IJKL"])
def test_real_secret_is_saved(value):
    assert not ChannelsHandler._is_masked_secret(value)


@pytest.mark.parametrize("value", ["", None])
def test_empty_value_is_skipped(value):
    assert ChannelsHandler._is_masked_secret(value)
