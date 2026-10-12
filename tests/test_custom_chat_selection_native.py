"""Chat model selection via the Models API persists correctly and reaches the HTTP wire."""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

# Runs in a subprocess so the real web.py is used instead of the suite's optional-framework stubs.
_PRELUDE = """
import json, os
from pathlib import Path
import config
import web
from channel.web.api.models import ModelsHandler
from models.chatgpt.chat_gpt_bot import ChatGPTBot
path = Path(os.environ['COW_DATA_DIR']) / 'config.json'
def select(provider_id, model):
    app = web.application(('/api/models', 'ModelsHandler'), {'ModelsHandler': ModelsHandler})
    payload = {'action': 'set_capability', 'capability': 'chat', 'provider_id': provider_id, 'model': model}
    response = app.request('/api/models', method='POST', data=json.dumps(payload),
                           headers={'Content-Type': 'application/json'})
    assert response.status.startswith('200') and json.loads(response.data)['status'] == 'success', response.data
    return json.loads(path.read_text())
"""


def _run(tmp_path, config, code, **env):
    (tmp_path / "config.json").write_text(json.dumps(dict(
        config, agent=False, web_password="", agent_workspace=str(tmp_path / "workspace"))), encoding="utf-8")
    env = dict({k: v for k, v in os.environ.items() if k != "MODEL"}, COW_DATA_DIR=str(tmp_path), **env)
    result = subprocess.run([sys.executable, "-c", _PRELUDE + code], env=env,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.splitlines()[-1])


@pytest.fixture
def endpoint():
    captured = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            captured.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = json.dumps({"choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": "owned response"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1", captured
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


@pytest.mark.parametrize("provider_id,default,selected,env_model", [
    ("custom:owned", "provider-default", "selected-model", ""),
    ("custom:owned", "provider-default", "", ""),
    ("custom:owned", "", "selected-model", ""),
    ("custom:owned", "provider-default", "selected-model", "environment-model"),
    ("custom", "provider-default", "selected-model", ""),
    ("openai", "provider-default", "selected-model", ""),
])
def test_main_model_selection_reaches_native_wire(tmp_path, endpoint, provider_id, default, selected, env_model):
    url, captured = endpoint
    providers = [
        {"id": "owned", "name": "Owned", "api_base": url, "api_key": "owned-fixture-key", "model": default},
        {"id": "other", "name": "Other", "api_base": url, "api_key": "other-fixture-key",
         "model": "other-default", "extra": "retained"},
    ]
    config = {"model": "global-model", "bot_type": provider_id, "custom_providers": providers,
              "custom_api_base": url, "custom_api_key": "legacy-fixture-key",
              "open_ai_api_base": url, "open_ai_api_key": "openai-fixture-key"}
    output = _run(tmp_path, config, """
config.config = config.Config(json.loads(path.read_text()))
saved = select(os.environ['PROVIDER'], os.environ['SELECTED'])
config.config = config.Config(saved)
if os.environ.get('MODEL'):
    config.load_config()
messages = [{'role': 'user', 'content': 'owned prompt'}]
reply = ChatGPTBot(bot_type=os.environ['PROVIDER']).call_with_tools(messages, stream=False)
assert reply['choices'][0]['message']['content'] == 'owned response'
other = ChatGPTBot(bot_type='custom:other')
other.call_with_tools(messages, stream=False)
other.call_with_tools(messages, stream=False, model='explicit-fallback')
print(json.dumps({'saved': saved, 'loaded_model': config.conf().get('model')}))
""", PROVIDER=provider_id, SELECTED=selected, **({"MODEL": env_model} if env_model else {}))
    saved, expected = output["saved"], selected or default
    assert saved["model"] == expected
    assert output["loaded_model"] == (env_model or expected)
    assert saved["custom_providers"][1] == providers[1]
    assert [r["model"] for r in captured] == [expected, "other-default", "explicit-fallback"]
    if provider_id == "custom:owned" and selected and default:
        assert saved["custom_providers"][0]["model"] == selected
    elif provider_id != "custom:owned" or not selected:
        assert saved["custom_providers"][0] == providers[0]


@pytest.mark.parametrize("env_only", [False, True])
def test_model_selection_keeps_environment_providers_out_of_file(tmp_path, env_only):
    provider_id = "env-only" if env_only else "owned"
    stored = [
        {"id": "owned", "name": "Stored", "api_key": "stored-fixture-key",
         "api_base": "https://stored.invalid/v1", "model": "stored-default", "extra": "keep"},
        {"id": "other", "name": "Other stored", "model": "other-default"},
        {"legacy_unknown": "retain"},
    ]
    runtime = [{"id": provider_id, "name": "Environment provider", "api_key": "env-only-fixture-key",
                "api_base": "https://env.invalid/v1", "model": "environment-default"},
               {"id": "env-other", "api_key": "other-env-only-fixture-key"}]
    output = _run(tmp_path, {"custom_providers": stored, "model": "global-model", "bot_type": "custom:" + provider_id},
                  """
config.load_config()
saved = select(config.conf()['bot_type'], 'selected-model')
config.load_config()
print(json.dumps({'saved': saved, 'reloaded_model': ChatGPTBot().get_api_config()['model']}))
""", CUSTOM_PROVIDERS=json.dumps(runtime))
    saved = output["saved"]["custom_providers"]
    assert output["saved"]["model"] == "selected-model"
    assert saved[1:] == stored[1:]
    assert dict(saved[0], model=None) == dict(stored[0], model=None)
    assert saved[0]["model"] == ("stored-default" if env_only else "selected-model")
    assert "env-only-fixture-key" not in (tmp_path / "config.json").read_text()
    assert output["reloaded_model"] == "environment-default"
