"""Exercise the real Models API, persisted configuration and local HTTP wire."""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


@pytest.mark.parametrize("provider_id,default,selected,env_model", [
    ("custom:owned", "provider-default", "selected-model", ""),
    ("custom:owned", "provider-default", "", ""),
    ("custom:owned", "", "selected-model", ""),
    ("custom:owned", "provider-default", "selected-model", "environment-model"),
    ("custom", "provider-default", "selected-model", ""),
    ("openai", "provider-default", "selected-model", ""),
])
def test_main_model_selection_reaches_native_wire(
    tmp_path, provider_id, default, selected, env_model,
):
    captured = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured.append(request)
            body = json.dumps({
                "id": "owned-response", "object": "chat.completion", "created": 0,
                "model": request["model"],
                "choices": [{"index": 0, "message": {
                    "role": "assistant", "content": "owned response",
                }, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }).encode()
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
    endpoint = "http://127.0.0.1:" + str(server.server_port) + "/v1"
    providers = [
        {"id": "owned", "name": "Owned", "api_base": endpoint,
         "api_key": "owned-fixture-key", "model": default},
        {"id": "other", "name": "Other", "api_base": endpoint,
         "api_key": "other-fixture-key", "model": "other-default", "extra": "retained"},
    ]
    initial = {
        "model": "global-model", "bot_type": provider_id, "custom_providers": providers,
        "custom_api_base": endpoint, "custom_api_key": "legacy-fixture-key",
        "open_ai_api_base": endpoint, "open_ai_api_key": "openai-fixture-key",
        "agent_workspace": str(tmp_path / "workspace"), "agent": False, "web_password": "",
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(initial), encoding="utf-8")
    payload = {"action": "set_capability", "capability": "chat",
               "provider_id": provider_id, "model": selected}
    # Isolate the real web.py module from the suite's optional-framework stubs.
    code = """
import json, os
from pathlib import Path
import config
import web
from channel.web.api.models import ModelsHandler
from models.chatgpt.chat_gpt_bot import ChatGPTBot
path = Path(os.environ['COW_DATA_DIR']) / 'config.json'
config.config = config.Config(json.loads(path.read_text()))
app = web.application(('/api/models', 'ModelsHandler'), {'ModelsHandler': ModelsHandler})
response = app.request('/api/models', method='POST', data=os.environ['OWNED_PAYLOAD'],
                       headers={'Content-Type': 'application/json'})
assert response.status.startswith('200'), response.status
assert json.loads(response.data)['status'] == 'success', response.data
saved = json.loads(path.read_text())
config.config = config.Config(saved)
if os.environ.get('MODEL'):
    config.load_config()
bot = ChatGPTBot(bot_type=os.environ['OWNED_PROVIDER'])
messages = [{'role': 'user', 'content': 'owned prompt'}]
reply = bot.call_with_tools(messages, stream=False)
assert reply['choices'][0]['message']['content'] == 'owned response'
other = ChatGPTBot(bot_type='custom:other')
other.call_with_tools(messages, stream=False)
other.call_with_tools(messages, stream=False, model='explicit-fallback')
print(json.dumps({'saved': saved, 'loaded_model': config.conf().get('model')}))
"""
    env = dict(os.environ, COW_DATA_DIR=str(tmp_path), OWNED_PROVIDER=provider_id,
               OWNED_PAYLOAD=json.dumps(payload))
    env.pop("MODEL", None)
    if env_model:
        env["MODEL"] = env_model
    try:
        result = subprocess.run([sys.executable, "-c", code], env=env,
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        output = json.loads(result.stdout.splitlines()[-1])
        saved = output["saved"]
        expected = selected or default
        assert saved["model"] == expected
        assert output["loaded_model"] == (env_model or expected)
        assert saved["custom_providers"][1] == providers[1]
        assert [r["model"] for r in captured] == [
            expected, "other-default", "explicit-fallback",
        ]
        if provider_id == "custom:owned" and selected and default:
            assert saved["custom_providers"][0]["model"] == selected
        elif provider_id != "custom:owned" or not selected:
            assert saved["custom_providers"][0] == providers[0]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize("env_only", [False, True])
def test_model_selection_keeps_environment_providers_out_of_file(tmp_path, env_only):
    provider_id = "env-only" if env_only else "owned"
    stored = [
        {"id": "owned", "name": "Stored", "api_key": "stored-fixture-key",
         "api_base": "https://stored.invalid/v1", "model": "stored-default", "extra": "keep"},
        {"id": "other", "name": "Other stored", "model": "other-default"},
        {"legacy_unknown": "retain"},
    ]
    initial = {"custom_providers": stored, "model": "global-model",
               "bot_type": "custom:" + provider_id, "agent": False,
               "agent_workspace": str(tmp_path / "workspace"), "web_password": ""}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(initial), encoding="utf-8")
    runtime = [{"id": provider_id, "name": "Environment provider",
                "api_key": "env-only-fixture-key", "api_base": "https://env.invalid/v1",
                "model": "environment-default"},
               {"id": "env-other", "api_key": "other-env-only-fixture-key"}]
    code = """
import json, os
from pathlib import Path
import config
import web
from channel.web.api.models import ModelsHandler
from models.chatgpt.chat_gpt_bot import ChatGPTBot
config.load_config()
app = web.application(('/api/models', 'ModelsHandler'), {'ModelsHandler': ModelsHandler})
payload = {'action': 'set_capability', 'capability': 'chat',
           'provider_id': config.conf()['bot_type'], 'model': 'selected-model'}
response = app.request('/api/models', method='POST', data=json.dumps(payload),
                       headers={'Content-Type': 'application/json'})
assert json.loads(response.data)['status'] == 'success', response.data
path = Path(os.environ['COW_DATA_DIR']) / 'config.json'
saved = json.loads(path.read_text())
config.load_config()
model = ChatGPTBot().get_api_config()['model']
print(json.dumps({'saved': saved, 'reloaded_model': model}))
"""
    env = dict(os.environ, COW_DATA_DIR=str(tmp_path), CUSTOM_PROVIDERS=json.dumps(runtime))
    env.pop("MODEL", None)
    result = subprocess.run([sys.executable, "-c", code], env=env,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(result.stdout.splitlines()[-1])
    saved = output["saved"]
    assert saved["model"] == "selected-model"
    assert len(saved["custom_providers"]) == len(stored)
    assert saved["custom_providers"][1:] == stored[1:]
    assert {k: v for k, v in saved["custom_providers"][0].items() if k != "model"} == {
        k: v for k, v in stored[0].items() if k != "model"
    }
    if env_only:
        assert saved["custom_providers"] == stored
    else:
        assert saved["custom_providers"][0]["model"] == "selected-model"
    assert "env-only-fixture-key" not in path.read_text()
    assert output["reloaded_model"] == "environment-default"
