"""The explicitly selectable, non-durable local execution backend."""

from __future__ import annotations

from collections.abc import Awaitable, Callable


class LocalExecution:
    """Run transition code in the awaiting caller's process.

    This adapter deliberately performs no queuing, leases, retrying, or crash
    recovery. It only defines what the caller waits for in the MVP profile.
    """

    async def run(self, callback: Callable[..., object], **inputs: object) -> object:
        value = callback(**inputs)
        return await value if isinstance(value, Awaitable) else value
