"""In-memory per-run event broadcast feeding the SSE endpoint."""
import asyncio
from collections import defaultdict


class Broadcaster:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, run_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs[run_id].add(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        self._subs.get(run_id, set()).discard(q)

    def publish(self, run_id: str, event: dict) -> None:
        for q in list(self._subs.get(run_id, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # slow consumer: drop rather than block the pipeline


broadcaster = Broadcaster()
