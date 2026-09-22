"""An in-process transport for tests and a mock store server: no network."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]


class InMemoryTransport:
    """Routes JSON-RPC payloads to a handler that returns response objects."""

    def __init__(self, handler: Handler) -> None:
        self._handler = handler
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    async def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.sent.append(payload)
        result = self._handler(payload)
        if hasattr(result, "__await__"):
            result = await result  # type: ignore[assignment]
        return result  # type: ignore[return-value]

    async def notify(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)
        result = self._handler(payload)
        if hasattr(result, "__await__"):
            await result  # type: ignore[misc]

    async def aclose(self) -> None:
        self.closed = True
