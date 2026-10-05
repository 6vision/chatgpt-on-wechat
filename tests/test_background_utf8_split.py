import subprocess
import sys
import threading
import time

from agent.tools.bash import background


def test_native_pipe_split_utf8_is_retained_until_the_character_is_complete():
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'\\xe4'); sys.stdout.buffer.flush(); sys.stdin.buffer.read(1); sys.stdout.buffer.write(b'\\xb8\\xad'); sys.stdout.buffer.flush()",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    job = background._Job("native", "fixture", process)
    reader = threading.Thread(target=background._drain, args=(job, process.stdout), daemon=True)
    job.readers.append(reader)
    reader.start()
    try:
        deadline = time.monotonic() + 5
        while len(job.buffer) < 1 and time.monotonic() < deadline:
            time.sleep(0.001)
        assert bytes(job.buffer) == b"\xe4"
        partial, dropped = job.take_new_output()
        assert partial == ""
        assert dropped == 0
        process.stdin.write(b"x")
        process.stdin.flush()
        process.wait(timeout=5)
        reader.join(5)
        final, dropped = job.take_new_output()
        assert final == "中"
        assert dropped == 0
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        reader.join(5)
        process.stdin.close()
        process.stdout.close()


def test_finished_native_pipe_flushes_an_incomplete_final_byte():
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\xe4')"], stdout=subprocess.PIPE
    )
    job = background._Job("native-final", "fixture", process)
    reader = threading.Thread(target=background._drain, args=(job, process.stdout), daemon=True)
    job.readers.append(reader)
    reader.start()
    process.wait(timeout=5)
    reader.join(5)
    with background._lock:
        background._jobs[job.id] = job
    try:
        result = background.read(job.id)
        assert result["running"] is False
        assert result["output"] == "�"
    finally:
        with background._lock:
            background._jobs.pop(job.id, None)
        process.stdout.close()
