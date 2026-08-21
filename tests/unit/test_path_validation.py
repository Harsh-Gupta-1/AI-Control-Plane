import pytest
from control_plane.tools.path_validation import validate_sandbox_path

def test_validate_sandbox_path_valid():
    assert validate_sandbox_path("/workspace/file.txt") == "/workspace/file.txt"
    assert validate_sandbox_path("file.txt") == "/workspace/file.txt"
    assert validate_sandbox_path("/downloads/test.jpg") == "/downloads/test.jpg"
    assert validate_sandbox_path("/workspace/sub/dir/file") == "/workspace/sub/dir/file"
    assert validate_sandbox_path("./file.txt") == "/workspace/file.txt"

def test_validate_sandbox_path_traversal():
    with pytest.raises(ValueError, match="outside sandbox boundaries"):
        validate_sandbox_path("../etc/passwd")
    
    with pytest.raises(ValueError, match="outside sandbox boundaries"):
        validate_sandbox_path("/workspace/../../etc/passwd")

    with pytest.raises(ValueError, match="outside sandbox boundaries"):
        validate_sandbox_path("/etc/shadow")

def test_validate_sandbox_path_windows():
    with pytest.raises(ValueError, match="Windows paths are not allowed"):
        validate_sandbox_path("C:\\Windows\\System32")
    
    with pytest.raises(ValueError, match="Windows paths are not allowed"):
        validate_sandbox_path("C:/Windows/System32")
        
    with pytest.raises(ValueError, match="Windows paths are not allowed"):
        validate_sandbox_path("\\\\server\\share")

def test_validate_sandbox_path_empty():
    with pytest.raises(ValueError, match="path must be a non-empty string"):
        validate_sandbox_path("")
        
    with pytest.raises(ValueError, match="path must be a non-empty string"):
        validate_sandbox_path(None)
