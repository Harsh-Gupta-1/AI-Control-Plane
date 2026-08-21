from datetime import datetime, timezone
from copy import deepcopy
import threading

from control_plane.domain.models import ApprovalRequest, ApprovalDecision, ApprovalStatus, ApprovalGrant
from control_plane.approval.contracts import ApprovalStore

class ApprovalNotFoundError(KeyError):
    pass

class InMemoryApprovalStore(ApprovalStore):
    """Simple in-memory approval store for the MVP."""
    def __init__(self) -> None:
        self._requests: dict[str, ApprovalRequest] = {}
        self._events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def create_request(self, request: ApprovalRequest) -> ApprovalRequest:
        req = deepcopy(request)
        if not req.created_at:
            req.created_at = datetime.now(timezone.utc)
        
        with self._lock:
            self._requests[req.approval_id] = req
            self._events[req.approval_id] = threading.Event()
            
        return deepcopy(req)

    def get_request(self, approval_id: str) -> ApprovalRequest:
        with self._lock:
            if approval_id not in self._requests:
                raise ApprovalNotFoundError(f"Approval {approval_id} not found")
            return deepcopy(self._requests[approval_id])

    def get_grant(self, approval_id: str) -> ApprovalGrant | None:
        with self._lock:
            if approval_id not in self._requests:
                return None
            req = self._requests[approval_id]
        
        import json
        import hashlib
        
        # Consistent JSON string for hash
        args_json = json.dumps(req.arguments, sort_keys=True)
        args_hash = hashlib.sha256(args_json.encode("utf-8")).hexdigest()
        
        return ApprovalGrant(
            approval_id=req.approval_id,
            request_id=req.request_id,
            capability=req.capability,
            arguments_hash=args_hash,
            status=req.status
        )

    def resolve(self, decision: ApprovalDecision) -> ApprovalRequest:
        with self._lock:
            if decision.approval_id not in self._requests:
                raise ApprovalNotFoundError(f"Approval {decision.approval_id} not found")
                
            req = self._requests[decision.approval_id]
            if req.status != ApprovalStatus.PENDING:
                raise ValueError(f"Approval {decision.approval_id} is already resolved")
                
            req.status = ApprovalStatus.APPROVED if decision.approved else ApprovalStatus.REJECTED
            req.resolved_at = datetime.now(timezone.utc)
            req.resolved_by = "human" # Simplified for MVP
            
            event = self._events.get(decision.approval_id)
            
        if event:
            event.set()
            
        return deepcopy(req)

    def wait_for_resolution(self, approval_id: str, timeout_seconds: float) -> ApprovalRequest:
        with self._lock:
            if approval_id not in self._requests:
                raise ApprovalNotFoundError(f"Approval {approval_id} not found")
            event = self._events[approval_id]
            req = self._requests[approval_id]
            
            if req.status != ApprovalStatus.PENDING:
                return deepcopy(req)

        # Wait without holding lock
        resolved = event.wait(timeout=timeout_seconds)
        
        with self._lock:
            req = self._requests[approval_id]
            if not resolved and req.status == ApprovalStatus.PENDING:
                req.status = ApprovalStatus.EXPIRED
                req.resolved_at = datetime.now(timezone.utc)
                req.resolved_by = "system_timeout"
            return deepcopy(req)

    def get_pending_for_task(self, task_id: str) -> list[ApprovalRequest]:
        with self._lock:
            return [
                deepcopy(req) for req in self._requests.values()
                if req.task_id == task_id and req.status == ApprovalStatus.PENDING
            ]

class DefaultApprovalAuthorizer:
    def __init__(self, store: ApprovalStore):
        self._store = store

    def authorize(self, request, approval_id: str) -> bool:
        grant = self._store.get_grant(approval_id)
        if not grant:
            return False
            
        import json, hashlib
        args_json = json.dumps(request.arguments, sort_keys=True)
        args_hash = hashlib.sha256(args_json.encode("utf-8")).hexdigest()
        
        if grant.status != ApprovalStatus.APPROVED:
            return False
        if grant.request_id != request.request_id:
            return False
        if grant.capability != request.capability:
            return False
        if grant.arguments_hash != args_hash:
            return False
            
        return True
