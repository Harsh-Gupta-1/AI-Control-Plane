"""Path validation utilities for sandbox tools."""
import posixpath

ALLOWED_ROOTS = ("/workspace", "/downloads", "/input", "/output", "/temp", "/shared")

def validate_sandbox_path(path: str) -> str:
    """Normalize and validate a path is within sandbox boundaries.
    
    Returns the normalized absolute path.
    Raises ValueError if the path escapes sandbox boundaries.
    """
    if not path or not isinstance(path, str):
        raise ValueError("path must be a non-empty string")
    
    # Reject Windows-style paths
    if "\\" in path or (len(path) >= 2 and path[1] == ":"):
        raise ValueError(f"Windows paths are not allowed: {path}")
    
    # Make absolute under /workspace if relative
    if not path.startswith("/"):
        path = posixpath.join("/workspace", path)
    
    # Normalize to resolve .. and .
    normalized = posixpath.normpath(path)
    
    # Check against allowed roots
    if not any(normalized == root or normalized.startswith(root + "/") for root in ALLOWED_ROOTS):
        raise ValueError(f"path is outside sandbox boundaries: {normalized}")
    
    return normalized
