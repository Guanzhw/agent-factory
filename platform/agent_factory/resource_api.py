from fastapi import APIRouter, Request
from pydantic import Field, StrictInt
from .factory_api import Body


class Attach(Body):
    connectionRef: str = Field(min_length=1, max_length=100)
    taskId: str | None = None
    requestId: str | None = None


class Allocate(Body):
    connectionRef: str = Field(min_length=1, max_length=100)
    taskId: str
    requestId: str
    limits: dict[str, StrictInt]


class Maintenance(Body):
    after: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


def resource_router(auth, resources, maintenance=None):
    router = APIRouter(prefix="/api/factory/resources")

    def owner(request):
        user = auth.user(request)
        auth.require(user["id"], "run")
        return user["id"]

    @router.get("")
    def discover(request: Request):
        return resources.discover(owner(request))

    @router.get("/leases")
    def leases(request: Request, after: str | None = None):
        return resources.list_leases(owner(request), after=after)

    @router.post("/attach")
    async def attach(body: Attach, request: Request):
        return await resources.attach(owner(request), body.connectionRef, body.taskId, body.requestId)

    @router.post("/allocate")
    async def allocate(body: Allocate, request: Request):
        return await resources.allocate(owner(request), body.connectionRef, body.taskId, body.requestId, body.limits)

    @router.post("/maintenance")
    async def maintain(request: Request, body: Maintenance | None = None):
        user = auth.user(request)
        auth.require(user["id"], "agent_os:admin")
        if maintenance is None:
            from fastapi import HTTPException
            raise HTTPException(409, "Resource maintenance is unavailable")
        return await maintenance.sweep(user["id"], limit=20, after=body.after if body is not None else None)

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
