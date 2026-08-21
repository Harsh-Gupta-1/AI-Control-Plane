import json
import urllib.request
import urllib.error
from control_plane.llm.contracts import LLMProvider, AgentContext, LLMProposal, ProposalAction, LLMError
from control_plane.domain import ToolRequest

SYSTEM_PROMPT = """You are an AI assistant orchestrating a task inside a sandbox environment.
You will be given the context of the current task, including available tools and recent observations.
You must respond ONLY with a valid JSON object matching the following schema, with no markdown formatting or extra text.

CRITICAL RULES:
1. NEVER omit required fields. If an action requires a field, it MUST be present.
2. When choosing "complete", you MUST provide a "completion_reason" explaining what you accomplished.
3. Unless using a specific shared directory, ALWAYS write files to `/workspace/`. Do NOT write to `/sandbox/`, `/tmp/`, or `/`.

Schema:
{
    "action": "plan|tool_call|complete|give_up",
    "reasoning": "Brief explanation of your choice",
    "plan_steps": ["step 1", "step 2"], // Required if action is "plan", otherwise null
    "tool_request": {                   // Required if action is "tool_call", otherwise null
        "tool_name": "name",
        "capability": "capability_name",
        "arguments": {"arg1": "value"}
    },
    "completion_reason": "Detailed explanation of the final result"  // Required if action is "complete" or "give_up", otherwise null
}
"""

class GroqProvider(LLMProvider):
    """Groq API adapter implementing LLMProvider."""
    
    def __init__(self, api_key: str, model: str = "qwen/qwen3.6-27b", max_retries: int = 2) -> None:
        self._api_key = api_key
        self._model = model
        self._max_retries = max_retries
        self._base_url = "https://api.groq.com/openai/v1/chat/completions"
        
    def _format_prompt(self, context: AgentContext) -> str:
        prompt = f"TASK GOAL: {context.task_goal}\n\n"
        if context.plan_summary:
            prompt += f"PLAN SUMMARY: {context.plan_summary}\n\n"
        if context.current_step:
            prompt += f"CURRENT STEP: {context.current_step}\n\n"
            
        prompt += "AVAILABLE TOOLS:\n"
        for tool in context.available_tools:
            prompt += f"- {json.dumps(tool)}\n"
            
        prompt += "\nCOMPLETED ACTIONS:\n"
        for action in context.completed_actions:
            prompt += f"- {json.dumps(action)}\n"
            
        prompt += "\nRECENT OBSERVATIONS:\n"
        for obs in context.recent_observations:
            prompt += f"- {json.dumps(obs)}\n"
            
        if context.error_context:
            prompt += f"\nERROR CONTEXT (Fix this!): {context.error_context}\n"
            
        return prompt

    def propose(self, context: AgentContext) -> LLMProposal:
        prompt = self._format_prompt(context)
        
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"}
        }
        
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "User-Agent": "ControlPlaneAgent/1.0"
        }
        
        retries = 0
        last_error = None
        
        while retries <= self._max_retries:
            try:
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(self._base_url, data=data, headers=headers)
                
                with urllib.request.urlopen(req, timeout=30) as response:
                    body = response.read().decode("utf-8")
                    result = json.loads(body)
                    
                content = result["choices"][0]["message"]["content"]
                
                try:
                    parsed = json.loads(content)
                    return self._parse_proposal(parsed)
                except (json.JSONDecodeError, ValueError, KeyError) as e:
                    last_error = f"Malformed output: {e}"
                    retries += 1
                    payload["messages"].append({"role": "assistant", "content": content})
                    payload["messages"].append({"role": "user", "content": f"Your output was malformed. Fix this error and return valid JSON matching the schema: {e}"})
                    
            except urllib.error.URLError as e:
                # Give more detailed error message for groq API errors if available
                if hasattr(e, 'read'):
                    err_body = e.read().decode('utf-8')
                    raise LLMError(f"Connection to Groq failed: {e}. Body: {err_body}") from e
                raise LLMError(f"Connection to Groq failed: {e}") from e
            except Exception as e:
                raise LLMError(f"Unexpected provider error: {e}") from e
                
        return LLMProposal(
            action=ProposalAction.GIVE_UP, 
            reasoning="malformed model output",
            completion_reason=last_error
        )

    def _parse_proposal(self, data: dict) -> LLMProposal:
        action_str = data.get("action", "")
        try:
            action = ProposalAction(action_str)
        except ValueError:
            raise ValueError(f"Invalid action: {action_str}")
            
        proposal = LLMProposal(
            action=action,
            reasoning=data.get("reasoning", "")
        )
        
        if action == ProposalAction.PLAN:
            steps = data.get("plan_steps")
            if not isinstance(steps, list):
                raise ValueError("plan_steps must be a list for PLAN action")
            proposal.plan_steps = steps
            
        elif action == ProposalAction.TOOL_CALL:
            tr_data = data.get("tool_request")
            if not isinstance(tr_data, dict):
                raise ValueError("tool_request must be an object for TOOL_CALL action")
            proposal.tool_request = ToolRequest(
                tool_name=tr_data.get("tool_name", ""),
                capability=tr_data.get("capability", ""),
                arguments=tr_data.get("arguments", {})
            )
            
        elif action in (ProposalAction.COMPLETE, ProposalAction.GIVE_UP):
            proposal.completion_reason = data.get("completion_reason")
            
        return proposal
