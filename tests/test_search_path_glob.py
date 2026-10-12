import subprocess
import sys
import time
import pytest
from agent.tools.search_files.search_files import SearchFiles, _SearchOptions

@pytest.mark.parametrize("glob, expected", [("src/*.py", ["src/direct.py"]), ("**/*.py", ["root.py", "src/direct.py", "src/nested/deep.py"]), ("src/**/*.{py,txt}", ["src/direct.py", "src/nested/deep.py", "src/note.txt"])])
def test_native_python_backend_honors_path_filters(tmp_path, glob, expected):
    for path in ["root.py", "src/direct.py", "src/nested/deep.py", "src/note.txt"]:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("needle")
    tool = SearchFiles({"cwd": str(tmp_path)})
    options = _SearchOptions("needle", str(tmp_path), glob, "content", False, False, 50, time.monotonic()+5)
    result = tool._backend_python(options)
    assert [row["file"] for row in result.rows] == expected

def test_native_repeated_recursive_globs_finish_within_deadline(tmp_path):
    target = tmp_path.joinpath(*(["deep"] * 18), "found.py")
    target.parent.mkdir(parents=True)
    target.write_text("needle")
    code = """import sys,types,pathlib,time
package=types.ModuleType('agent'); package.__path__=[str(pathlib.Path.cwd()/'agent')]; sys.modules['agent']=package
from agent.tools.search_files.search_files import SearchFiles,_SearchOptions
tool=SearchFiles({'cwd':sys.argv[1]})
options=_SearchOptions('needle',sys.argv[1],'/'.join(['**']*18+['missing.py']),'content',False,False,50,time.monotonic()+1)
assert tool._backend_python(options).rows == []
print('finished')
"""
    process = subprocess.Popen([sys.executable, "-c", code, str(tmp_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        try:
            stdout, stderr = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            pytest.fail("Repeated recursive path globs exceeded the subprocess deadline")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    assert process.returncode == 0, stderr
    assert "finished" in stdout
