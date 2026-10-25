"""Bounded application reconciliation; Agno owns all task execution."""
import asyncio

from fastapi import HTTPException
from sqlalchemy import select


class IterationCoordinator:
    def __init__(self, service):
        self.service = service
        self.active = {}
        self._stop = asyncio.Event()
        self._task = None
        self._cursor = ''
        self.last_error_type = None

    def start(self):
        if self._task is not None:
            raise RuntimeError('ITERATION_COORDINATOR_ALREADY_STARTED')
        self._task = asyncio.create_task(self._run())

    def stop_admission(self):
        self.service.accepting = False
        self._stop.set()

    def _batch(self):
        service = self.service
        with service.store.transaction(read_only=True) as conn:
            rows = conn.execute(select(service.activities.c.id, service.activities.c.owner_id)
                .where(service.activities.c.id > self._cursor, service.activities.c.body['status'].as_string() != 'stopped')
                .order_by(service.activities.c.id).limit(16)).all()
        self._cursor = rows[-1][0] if rows else ''
        return rows

    async def _one(self, owner, activity_id):
        try:
            self.service.auth.require_member(owner)
        except HTTPException as error:
            if error.status_code != 403:
                raise
            await self.service._retire_unavailable(owner, activity_id)
            return
        value = await self.service.reconcile(owner, activity_id)
        if value['activity']['status'] == 'ready' and self.service.accepting:
            previous = value['rounds'][-1]['id']
            await self.service.advance(owner, activity_id, previous, 'automatic-continue:' + previous)

    async def _run(self):
        while not self._stop.is_set():
            try:
                for identity, owner in await asyncio.to_thread(self._batch):
                    if self._stop.is_set():
                        break
                    task = asyncio.create_task(self._one(owner, identity))
                    self.active[identity] = task
                    try:
                        await task
                    except HTTPException as error:
                        # Revocation/expiry cannot authorize successor dispatch.
                        self.last_error_type = 'HTTP_' + str(error.status_code)
                    except Exception as error:
                        self.last_error_type = type(error).__name__
                    finally:
                        self.active.pop(identity, None)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.last_error_type = type(error).__name__
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=2)
            except TimeoutError:
                pass

    async def close(self, *, deadline):
        self.stop_admission()
        if self._task is None:
            return True
        done, pending = await asyncio.wait([self._task], timeout=max(0, deadline - asyncio.get_running_loop().time()))
        return not pending and all(not task.cancelled() and task.exception() is None for task in done)
