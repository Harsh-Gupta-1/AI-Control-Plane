"""Computer Manager to handle persistent computer lifecycles."""

import json
import os
from datetime import datetime, timezone
from typing import Any
import uuid

from control_plane.domain.models import ComputerSession, ComputerStatus
from control_plane.sandbox.contracts import SandboxError, SandboxState
from control_plane.sandbox.docker_sandbox import DockerSandbox

# Default storage location for persistent computer session metadata
DEFAULT_COMPUTERS_FILE = os.path.join(os.getcwd(), ".control_plane", "computers.json")


class ComputerManager:
    """Manages the lifecycle and metadata of persistent AI computer sessions."""

    def __init__(self, storage_path: str = DEFAULT_COMPUTERS_FILE) -> None:
        self._storage_path = storage_path
        self._ensure_storage()

    def _ensure_storage(self) -> None:
        """Ensure the storage directory and file exist."""
        os.makedirs(os.path.dirname(self._storage_path), exist_ok=True)
        if not os.path.exists(self._storage_path):
            with open(self._storage_path, "w") as f:
                json.dump({}, f)

    def _load_metadata(self) -> dict[str, dict[str, Any]]:
        """Load computer metadata from storage."""
        try:
            with open(self._storage_path, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_metadata(self, data: dict[str, dict[str, Any]]) -> None:
        """Save computer metadata to storage."""
        with open(self._storage_path, "w") as f:
            json.dump(data, f, indent=2)

    def _dict_to_session(self, data: dict[str, Any]) -> ComputerSession:
        return ComputerSession(
            id=data["id"],
            status=ComputerStatus(data["status"]),
            sandbox_id=data["sandbox_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            last_active_at=datetime.fromisoformat(data["last_active_at"]),
            metadata=data.get("metadata", {}),
        )

    def _session_to_dict(self, session: ComputerSession) -> dict[str, Any]:
        return {
            "id": session.id,
            "status": session.status.value,
            "sandbox_id": session.sandbox_id,
            "created_at": session.created_at.isoformat(),
            "last_active_at": session.last_active_at.isoformat(),
            "metadata": session.metadata,
        }

    def list_computers(self) -> list[ComputerSession]:
        """List all tracked computer sessions."""
        data = self._load_metadata()
        return [self._dict_to_session(v) for v in data.values()]

    def get_computer(self, computer_id: str) -> ComputerSession:
        """Get a computer session by ID."""
        data = self._load_metadata()
        if computer_id not in data:
            raise ValueError(f"Computer {computer_id} not found")
        
        session = self._dict_to_session(data[computer_id])
        
        # Optionally sync status with underlying sandbox
        if session.status not in {ComputerStatus.DESTROYED, ComputerStatus.ERROR}:
            try:
                sandbox = DockerSandbox()
                sandbox.attach(session.sandbox_id)
                state = sandbox.inspect()
                
                # Map sandbox state to computer status
                if state == SandboxState.RUNNING:
                    session.status = ComputerStatus.RUNNING
                elif state == SandboxState.STOPPED:
                    session.status = ComputerStatus.STOPPED
                elif state == SandboxState.DESTROYED:
                    session.status = ComputerStatus.DESTROYED
                elif state == SandboxState.CREATED:
                    session.status = ComputerStatus.READY
                    
                self.update_computer(session)
            except SandboxError:
                # If we fail to inspect, assume it's stopped/error
                pass
                
        return session

    def update_computer(self, session: ComputerSession) -> None:
        """Update a computer session in storage."""
        data = self._load_metadata()
        data[session.id] = self._session_to_dict(session)
        self._save_metadata(data)

    def create_computer(self, shared_dir: str | None = None) -> ComputerSession:
        """Create a new computer session (and underlying sandbox)."""
        sandbox = DockerSandbox(shared_dir=shared_dir)
        now = datetime.now(timezone.utc)
        
        session = ComputerSession(
            id=str(uuid.uuid4()),
            status=ComputerStatus.READY,
            sandbox_id=sandbox.id,
            created_at=now,
            last_active_at=now,
            metadata={"shared_dir": shared_dir} if shared_dir else {},
        )
        
        data = self._load_metadata()
        data[session.id] = self._session_to_dict(session)
        self._save_metadata(data)
        
        return session

    def start_computer(self, computer_id: str) -> DockerSandbox:
        """Start a computer session."""
        session = self.get_computer(computer_id)
        if session.status == ComputerStatus.DESTROYED:
            raise ValueError(f"Cannot start destroyed computer {computer_id}")
            
        sandbox = DockerSandbox(shared_dir=session.metadata.get("shared_dir"))
        sandbox.attach(session.sandbox_id)
        
        sandbox.start()
        
        session.status = ComputerStatus.RUNNING
        session.last_active_at = datetime.now(timezone.utc)
        self.update_computer(session)
        
        return sandbox

    def stop_computer(self, computer_id: str) -> None:
        """Stop a computer session."""
        session = self.get_computer(computer_id)
        if session.status in {ComputerStatus.DESTROYED, ComputerStatus.STOPPED}:
            return
            
        try:
            sandbox = DockerSandbox()
            sandbox.attach(session.sandbox_id)
            sandbox.stop()
        except SandboxError:
            pass # Already stopped or missing
            
        session.status = ComputerStatus.STOPPED
        session.last_active_at = datetime.now(timezone.utc)
        self.update_computer(session)

    def destroy_computer(self, computer_id: str) -> None:
        """Destroy a computer session and its sandbox."""
        session = self.get_computer(computer_id)
        if session.status == ComputerStatus.DESTROYED:
            return
            
        try:
            sandbox = DockerSandbox()
            sandbox.attach(session.sandbox_id)
            sandbox.destroy()
        except SandboxError:
            pass
            
        session.status = ComputerStatus.DESTROYED
        session.last_active_at = datetime.now(timezone.utc)
        self.update_computer(session)
        
    def get_sandbox(self, computer_id: str) -> DockerSandbox:
        """Get the underlying sandbox for a computer."""
        session = self.get_computer(computer_id)
        if session.status == ComputerStatus.DESTROYED:
            raise ValueError(f"Computer {computer_id} is destroyed")
            
        sandbox = DockerSandbox(shared_dir=session.metadata.get("shared_dir"))
        sandbox.attach(session.sandbox_id)
        return sandbox
