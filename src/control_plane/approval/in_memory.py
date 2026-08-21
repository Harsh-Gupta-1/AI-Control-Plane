from datetime import datetime, timezone
from copy import deepcopy

from control_plane.domain.models import ApprovalRequest, ApprovalDecision, ApprovalStatus
from control_plane.approval.contracts import ApprovalStore

class ApprovalNotFoundError(KeyError):
    pass

class InMemoryApprovalStore(ApprovalStore):
    """Simple in-memory approval store for the MVP."""
    def __init__(self) -> None:
        self._requests: dict[str, ApprovalRequest] = {}

    def create_request(self, request: ApprovalRequest) -> ApprovalRequest:
        req = deepcopy(request)
        if not req.created_at:
            req.created_at = datetime.now(timezone.utc)
        self._requests[req.approval_id] = req
        return deepcopy(req)

    def get_request(self, approval_id: str) -> ApprovalRequest:
        if approval_id not in self._requests:
            raise ApprovalNotFoundError(f"Approval {approval_id} not found")
        return deepcopy(self._requests[approval_id])

    def resolve(self, decision: ApprovalDecision) -> ApprovalRequest:
        if decision.approval_id not in self._requests:
            raise ApprovalNotFoundError(f"Approval {decision.approval_id} not found")
            
        req = self._requests[decision.approval_id]
        if req.status != ApprovalStatus.PENDING:
            raise ValueError(f"Approval {decision.approval_id} is already resolved")
            
        req.status = ApprovalStatus.APPROVED if decision.approved else ApprovalStatus.REJECTED
        req.resolved_at = datetime.now(timezone.utc)
        req.resolved_by = "human" # Simplified for MVP
        
        return deepcopy(req)

    def get_pending_for_task(self, task_id: str) -> list[ApprovalRequest]:
        return [
            deepcopy(req) for req in self._requests.values()
            if req.task_id == task_id and req.status == ApprovalStatus.PENDING
        ]
