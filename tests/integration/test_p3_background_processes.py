import pytest
import time
from control_plane.sandbox.docker_sandbox import DockerSandbox

@pytest.fixture
def sandbox():
    # Setup
    sb = DockerSandbox()
    sb.start()
    yield sb
    # Teardown
    sb.destroy()

def test_background_process_lifecycle(sandbox):
    # 1. Start a long running process
    # write to a file after 2 seconds
    bg_id = sandbox.execute_background(["sh", "-c", "sleep 2 && echo 'done' > /workspace/bg_result.txt && sleep 10"])
    
    # 2. Check status immediately
    status = sandbox.get_background_status(bg_id)
    assert status["status"] == "running"
    
    # 3. Wait for the file to be written
    time.sleep(3)
    
    # Check that file exists
    res = sandbox.execute(["cat", "/workspace/bg_result.txt"], timeout_seconds=5)
    assert res.stdout.strip() == "done"
    
    # 4. Status should still be running because it sleeps 10
    status = sandbox.get_background_status(bg_id)
    assert status["status"] == "running"
    
    # 5. Stop the process
    sandbox.stop_background(bg_id)
    
    # 6. Status should now be stopped
    status = sandbox.get_background_status(bg_id)
    assert status["status"] == "stopped"

def test_background_process_output_capture(sandbox):
    # Start a process that outputs some text
    bg_id = sandbox.execute_background(["sh", "-c", "echo 'hello background' && sleep 5"])
    
    # Wait for output to flush
    time.sleep(1)
    
    # Check status and output
    status = sandbox.get_background_status(bg_id)
    assert status["status"] == "running"
    assert "hello background" in status["stdout"]
    
    sandbox.stop_background(bg_id)
