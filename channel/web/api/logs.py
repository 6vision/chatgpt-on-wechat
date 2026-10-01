"""The logs view's endpoints: /api/logs.

Tails the log file for the terminal view and serves the whole file for
download.
"""

import json
import os
import time

import web

from channel.web.core._common import _require_auth
from common.log import logger
from common.utils import tail_lines
from config import get_data_root

_TAIL_LINE_LIMIT = 200


class LogsHandler:
    def GET(self):
        _require_auth()
        web.header('Content-Type', 'text/event-stream; charset=utf-8')
        web.header('Cache-Control', 'no-cache')
        web.header('X-Accel-Buffering', 'no')

        log_path = os.path.join(get_data_root(), "run.log")

        def generate():
            if not os.path.isfile(log_path):
                yield b"data: {\"type\": \"error\", \"message\": \"run.log not found\"}\n\n"
                return

            # Read last lines for initial display
            try:
                chunk = ''.join(tail_lines(log_path, _TAIL_LINE_LIMIT))
                payload = json.dumps({"type": "init", "content": chunk}, ensure_ascii=False)
                yield f"data: {payload}\n\n".encode('utf-8')
            except Exception as e:
                yield f"data: {{\"type\": \"error\", \"message\": \"{e}\"}}\n\n".encode('utf-8')
                return

            # Tail new lines
            try:
                with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                    f.seek(0, 2)  # seek to end
                    deadline = time.time() + 600  # 10 min max
                    while time.time() < deadline:
                        line = f.readline()
                        if line:
                            payload = json.dumps({"type": "line", "content": line}, ensure_ascii=False)
                            yield f"data: {payload}\n\n".encode('utf-8')
                        else:
                            yield b": keepalive\n\n"
                            time.sleep(1)
            except GeneratorExit:
                return
            except Exception:
                return

        return generate()


class LogsDownloadHandler:
    """Serve the full run.log as a file download for offline troubleshooting.

    The /api/logs stream only replays the last 200 lines; this returns the whole
    file so users can attach it to a bug report.
    """

    def GET(self):
        _require_auth()
        log_path = os.path.join(get_data_root(), "run.log")
        if not os.path.isfile(log_path):
            raise web.notfound()

        try:
            with open(log_path, 'rb') as f:
                data = f.read()
        except Exception as e:
            logger.error(f"[WebChannel] Log download error: {e}")
            raise web.internalerror()

        # Timestamped name so multiple downloads don't overwrite each other.
        fname = f"cowagent-{time.strftime('%Y%m%d-%H%M%S')}.log"
        web.header('Content-Type', 'text/plain; charset=utf-8')
        web.header('Content-Disposition', f'attachment; filename="{fname}"')
        web.header('Content-Length', str(len(data)))
        web.header('Cache-Control', 'no-store')
        return data
