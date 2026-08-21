import pytest
import os
import uuid
from datetime import datetime, timezone

from control_plane.domain.models import ComputerSession, ComputerStatus
from control_plane.sandbox.manager import ComputerManager

def test_computer_lifecycle(tmp_path):
    """Test creating, listing, and destroying computer sessions."""
    storage = tmp_path / "computers.json"
    manager = ComputerManager(storage_path=str(storage))
    
    # Initially empty
    assert len(manager.list_computers()) == 0
    
    # Create computer
    comp = manager.create_computer()
    assert comp.id is not None
    assert comp.status == ComputerStatus.READY
    
    # Verify persistence
    assert len(manager.list_computers()) == 1
    loaded = manager.get_computer(comp.id)
    assert loaded.id == comp.id
    assert loaded.status == ComputerStatus.READY
    
    # Start computer
    manager.start_computer(comp.id)
    assert manager.get_computer(comp.id).status == ComputerStatus.RUNNING
    
    # Stop computer
    manager.stop_computer(comp.id)
    assert manager.get_computer(comp.id).status == ComputerStatus.STOPPED
    
    # Destroy computer
    manager.destroy_computer(comp.id)
    assert manager.get_computer(comp.id).status == ComputerStatus.DESTROYED
