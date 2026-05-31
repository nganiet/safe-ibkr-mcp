"""Kill switch — instant freeze of all write operations.

Engaged if a runtime flag is set OR a sentinel file exists (default
~/.ibkr-mcp/KILL), so `touch ~/.ibkr-mcp/KILL` freezes trading without
touching the running process. Pure logic — no ib_async, no mcp.
"""

from pathlib import Path


class KillSwitchEngaged(Exception):
    """Raised when a write is attempted while the kill switch is engaged."""


_DEFAULT_PATH = Path.home() / ".ibkr-mcp" / "KILL"


class KillSwitch:
    def __init__(self, path: Path | None = None, *, armed: bool = False) -> None:
        self._path = path if path is not None else _DEFAULT_PATH
        self._runtime_armed = armed
        self._reason: str | None = "armed at startup" if armed else None

    def arm(self, reason: str) -> None:
        self._runtime_armed = True
        self._reason = reason

    def disarm(self) -> None:
        self._runtime_armed = False
        self._reason = None

    def is_engaged(self) -> bool:
        return self._runtime_armed or self._path.exists()

    def check(self) -> None:
        if not self.is_engaged():
            return
        reason = self._reason if self._runtime_armed else f"sentinel file {self._path}"
        raise KillSwitchEngaged(f"Kill switch engaged ({reason}) — writes blocked.")
