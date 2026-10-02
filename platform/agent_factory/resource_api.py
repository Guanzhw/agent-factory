from fastapi import APIRouter, Request
from pydantic import Field
from .factory_api import Body


class Attach(Body):
    connectionRef: str = Field(min_length=1, max_length=100)
    taskId: str | None = None
    requestId: str | None = None


class Allocate(Body):
    connectionRef: str = Field(min_length=1, max_length=100)
    taskId: str
    requestId: str
    limits: dict[str, int]


def resource_router(auth, resources):
    router = APIRouter(prefix="/api/factory/resources")

    def owner(request):
        user = auth.user(request)
        auth.require(user["id"], "run")
        return user["id"]

    @router.get("")
    def discover(request: Request):
        return resources.discover(owner(request))

    @router.post("/attach")
    async def attach(body: Attach, request: Request):
        return await resources.attach(owner(request), body.connectionRef, body.taskId, body.requestId)

    @router.post("/allocate")
    async def allocate(body: Allocate, request: Request):
        return await resources.allocate(owner(request), body.connectionRef, body.taskId, body.requestId, body.limits)

    @router.get("/leases/{lease_id}")
    def inspect(lease_id: str, request: Request):
        return resources.inspect(owner(request), lease_id)

    @router.post("/leases/{lease_id}/heartbeat")
    def heartbeat(lease_id: str, request: Request):
        return resources.heartbeat(owner(request), lease_id)

    @router.post("/leases/{lease_id}/disconnect")
    def disconnect(lease_id: str, request: Request):
        return resources.disconnect(owner(request), lease_id)

    @router.post("/leases/{lease_id}/reconcile")
    async def reconcile(lease_id: str, request: Request):
        return await resources.reconcile(owner(request), lease_id)

    @router.post("/leases/{lease_id}/cancel")
    async def cancel(lease_id: str, request: Request):
        return await resources.cancel(owner(request), lease_id)

    @router.post("/leases/{lease_id}/reclaim")
    async def reclaim(lease_id: str, request: Request):
        return await resources.reclaim(owner(request), lease_id)

    return router
