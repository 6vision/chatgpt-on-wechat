import json
import os
import subprocess
import sys
import pytest
from agent.tools.read.read import Read


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO fixture")
@pytest.mark.parametrize("alias", [False, True])
def test_read_fifo_returns_error_without_waiting_for_writer(tmp_path, alias):
    fifo = tmp_path / "pipe.txt"
    os.mkfifo(fifo)
    path = fifo
    if alias:
        path = tmp_path / "alias.txt"
        path.symlink_to(fifo)
    code = "from agent.tools.read.read import Read; import json,sys; print('ready', flush=True); r=Read({'cwd':sys.argv[1]}).execute({'path':sys.argv[2]}); print(json.dumps({'status':r.status,'error':r.result}))"
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(tmp_path), str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for line in process.stdout:
            if line.strip() == "ready":
                break
        else:
            pytest.fail("child exited before the FIFO read")
        output, error = process.communicate(timeout=2)
        assert process.returncode == 0, error
        assert json.loads(output)["status"] == "error"
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


def test_regular_text_and_symlink_remain_readable(tmp_path):
    source = tmp_path / "text.txt"
    source.write_text("hello", encoding="utf-8")
    link = tmp_path / "alias.txt"
    link.symlink_to(source)
    assert Read({"cwd": str(tmp_path)}).execute({"path": str(link)}).status == "success"
