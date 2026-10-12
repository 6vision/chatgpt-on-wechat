import json
import os
import subprocess
import sys
import pytest

@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires POSIX FIFO")
def test_native_fifo_cannot_block_python_search(tmp_path):
    os.mkfifo(tmp_path / "a.pipe")
    (tmp_path / "b.txt").write_text("needle")
    code = """import json,sys,types,pathlib
package=types.ModuleType('agent'); package.__path__=[str(pathlib.Path.cwd()/'agent')]; sys.modules['agent']=package
from agent.tools.search_files.search_files import SearchFiles
tool=SearchFiles({'cwd': sys.argv[1], 'timeout': 0.2})
tool._pick_backend=lambda: tool._backend_python
result=tool.execute({'pattern': 'needle'})
print(json.dumps({'status':result.status, 'result':result.result}))
"""
    process = subprocess.Popen([sys.executable, "-c", code, str(tmp_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        try:
            stdout, stderr = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            pytest.fail("Python search blocked opening a real FIFO despite its deadline")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    assert process.returncode == 0, stderr
    result = json.loads(stdout.strip().splitlines()[-1])
    assert result["status"] == "success"
    assert [row["file"] for row in result["result"]["matches"]] == ["b.txt"]
