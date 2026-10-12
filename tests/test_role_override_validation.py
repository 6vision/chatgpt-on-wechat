import json
import pytest
import plugins
plugins.instance.current_plugin_path = "./plugins/role"
from plugins.role import role as role_module  # noqa: F401 - import registers the decorated plugin
plugins.instance.current_plugin_path = None
Role = plugins.instance.plugins["ROLE"]


@pytest.mark.parametrize('tags', [None, 42, ['safe', {}], ['safe', []]])
def test_invalid_override_does_not_remove_previous_role(tmp_path, tags):
    plugin = Role.__new__(Role)
    original = {'title': 'Example', 'descs': ['Original'], 'tags': ['old']}
    plugin.roles = {'example': original}
    plugin.tags = {'old': ('Old', [original])}
    path = tmp_path / 'override.json'
    path.write_text(json.dumps({'title': 'New', 'descs': ['Replacement'], 'tags': tags}))
    plugin._load_role_file(str(path))
    assert plugin.roles['example'] is original
    assert plugin.tags['old'][1] == [original]
    assert 'safe' not in plugin.tags
    assert 'new' not in plugin.roles


def test_valid_override_updates_role_and_tag_membership(tmp_path):
    plugin = Role.__new__(Role)
    original = {'title': 'Example', 'descs': ['Original'], 'tags': ['old']}
    plugin.roles = {'example': original}
    plugin.tags = {'old': ('Old', [original])}
    replacement = {'title': 'Example', 'descs': ['Replacement'], 'tags': ['new']}
    path = tmp_path / 'override.json'
    path.write_text(json.dumps(replacement))
    plugin._load_role_file(str(path))
    assert plugin.roles['example'] == replacement
    assert plugin.tags['old'][1] == []
    assert plugin.tags['new'][1] == [replacement]
