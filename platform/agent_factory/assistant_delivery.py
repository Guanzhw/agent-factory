"""Bounded notification maintenance, sharing the native runtime's lifetime."""
import asyncio
from contextlib import asynccontextmanager
import logging


@asynccontextmanager
async def assistant_delivery_lifespan(service):
    stopping = asyncio.Event()
    service.admission_stopping = stopping

    async def run():
        while not stopping.is_set():
            try:
                await service.deliver_batch(stopping=stopping)
                service.delivery_error = None
            except Exception as error:
                service.delivery_error = type(error).__name__
                logging.getLogger(__name__).exception('Assistant notification delivery deferred')
            try:
                await asyncio.wait_for(stopping.wait(), timeout=1)
            except TimeoutError:
                pass

    task = asyncio.create_task(run(), name='assistant-notification-delivery')
    try:
        yield
    finally:
        stopping.set()
        # Finish the current metadata call before core disposes its database.
        await task
