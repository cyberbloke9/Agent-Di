"""A scripted, in-process CallTransport for testing calls without audio/network."""

from __future__ import annotations


class ScriptedCallTransport:
    def __init__(self, replies: list[str], caller_id: str = "+911140000000", hang_up_after: int | None = None) -> None:
        self._replies = list(replies)
        self._i = 0
        self._caller_id = caller_id
        self._connected = True
        self._hang_up_after = hang_up_after
        self.said: list[str] = []
        self.transferred = False
        self.hung_up = False

    @property
    def caller_id(self) -> str:
        return self._caller_id

    @property
    def connected(self) -> bool:
        return self._connected

    async def say_and_listen(self, text: str) -> str | None:
        self.said.append(text)
        if self._hang_up_after is not None and len(self.said) > self._hang_up_after:
            self._connected = False
            return None
        if self._i < len(self._replies):
            reply = self._replies[self._i]
            self._i += 1
            return reply
        self._connected = False
        return None

    async def say(self, text: str) -> None:
        self.said.append(text)

    async def transfer_to_user(self) -> bool:
        self.transferred = True
        return True

    async def hangup(self) -> None:
        self._connected = False
        self.hung_up = True
