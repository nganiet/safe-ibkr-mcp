"""MCP-layer configuration. No ib_async import here."""

import os
from dataclasses import dataclass
from collections.abc import Mapping

_TRUTHY = {"1", "true", "yes", "on"}


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 4002  # paper Gateway by default
    client_id: int = 1
    read_only: bool = True

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        env = os.environ if env is None else env
        return cls(
            host=env.get("IBKR_HOST", "127.0.0.1"),
            port=int(env.get("IBKR_PORT", "4002")),
            client_id=int(env.get("IBKR_CLIENT_ID", "1")),
            read_only=env.get("IBKR_READ_ONLY", "true").strip().lower() in _TRUTHY,
        )
