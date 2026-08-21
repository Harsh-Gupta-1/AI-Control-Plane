from control_plane.sandbox.contracts import Sandbox, SandboxState, SandboxResult, SandboxError

class FakeSandbox(Sandbox):
    """Test double that returns preconfigured results."""
    def __init__(self, results: list[SandboxResult]):
        self._results = list(results)
        self._started = False
        self._destroyed = False
        self._snapshots: set[str] = set()

    @property
    def id(self) -> str:
        return "fake-sandbox"

    def start(self) -> None:
        self.started = True
        self._started = True

    def attach(self, sandbox_id: str) -> None:
        self.attached = True

    def stop(self) -> None:
        pass

    def destroy(self) -> None:
        self._destroyed = True

    def snapshot(self) -> str:
        if self._destroyed or not self._started:
            raise SandboxError("Cannot snapshot a stopped or destroyed sandbox.")
        snapshot_id = f"snap-{len(self._snapshots)}"
        self._snapshots.add(snapshot_id)
        return snapshot_id

    def rollback(self, snapshot_id: str) -> None:
        if self._destroyed:
            raise SandboxError("Cannot rollback a destroyed sandbox.")
        if snapshot_id not in self._snapshots:
            raise SandboxError(f"Snapshot {snapshot_id} does not exist.")

    def inspect(self) -> SandboxState:
        return SandboxState.RUNNING

    def execute(self, command: list[str], timeout_seconds: int, max_output_bytes: int = 1048576) -> SandboxResult:
        if command and command[0] == "realpath":
            return SandboxResult(exit_code=0, stdout=command[-1], stderr="", timed_out=False, output_truncated=False)
            
        if not self._results:
            raise RuntimeError("FakeSandbox exhausted its preconfigured results")
        return self._results.pop(0)
