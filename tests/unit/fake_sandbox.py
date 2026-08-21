from control_plane.sandbox.contracts import Sandbox, SandboxState, SandboxResult

class FakeSandbox(Sandbox):
    """Test double that returns preconfigured results."""
    def __init__(self, results: list[SandboxResult]):
        self._results = list(results)

    @property
    def id(self) -> str:
        return "fake-sandbox"

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def destroy(self) -> None:
        pass

    def inspect(self) -> SandboxState:
        return SandboxState.RUNNING

    def execute(self, command: list[str], timeout_seconds: int, max_output_bytes: int = 1048576) -> SandboxResult:
        if command and command[0] == "realpath":
            return SandboxResult(exit_code=0, stdout=command[-1], stderr="", timed_out=False, output_truncated=False)
            
        if not self._results:
            raise RuntimeError("FakeSandbox exhausted its preconfigured results")
        return self._results.pop(0)
