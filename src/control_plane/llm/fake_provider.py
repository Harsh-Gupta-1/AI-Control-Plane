from control_plane.llm.contracts import AgentContext, LLMProposal, ProposalAction

class FakeLLMProvider:
    """Deterministic provider for testing the agent loop."""
    
    def __init__(self, proposals: list[LLMProposal]) -> None:
        self._proposals = list(proposals)
        self._call_count = 0
    
    def propose(self, context: AgentContext) -> LLMProposal:
        if self._call_count >= len(self._proposals):
            return LLMProposal(action=ProposalAction.GIVE_UP, reasoning="no more proposals")
        proposal = self._proposals[self._call_count]
        self._call_count += 1
        return proposal
