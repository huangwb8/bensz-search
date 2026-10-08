"""Bounded blocking work with context propagation and cancellation-safe completion."""

import asyncio
import contextvars
from concurrent.futures import ThreadPoolExecutor

import anyio


class BlockingWork:
    def __init__(self, workers=4, capacity=16):
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="search-store")
        self.slots = asyncio.Semaphore(capacity)
        self.pending = set()
        self.closed = False

    async def run(self, function, *args, **kwargs):
        async with self.slots:
            if self.closed:
                raise RuntimeError("Blocking work is closed")
            context = contextvars.copy_context()
            future = asyncio.get_running_loop().run_in_executor(
                self.executor, lambda: context.run(function, *args, **kwargs)
            )
            self.pending.add(future)
            cancelled = False
            try:
                with anyio.CancelScope(shield=True):
                    while True:
                        try:
                            result = await asyncio.shield(future)
                            break
                        except asyncio.CancelledError:
                            # SQLite cannot be interrupted by cancelling its waiter. Keep
                            # capacity reserved and observe commit/failure before releasing.
                            cancelled = True
                if cancelled:
                    raise asyncio.CancelledError
                return result
            finally:
                self.pending.discard(future)

    async def close(self):
        self.closed = True
        if self.pending:
            await asyncio.gather(*self.pending, return_exceptions=True)
        self.executor.shutdown(wait=True)
