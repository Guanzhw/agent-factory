from fastapi import APIRouter, Request
from pydantic import Field

from .factory_api import Body


class RetentionPlan(Body):
    objectId: str = Field(pattern=r"^[a-f0-9]{64}$")
    requestId: str = Field(min_length=8, max_length=100)


def storage_router(auth, storage):
    router = APIRouter(prefix="/api/factory/storage")

    @router.get("")
    async def summary(request: Request):
        return await storage.summary(auth.user(request)["id"])

    @router.post("/retention/plans", status_code=201)
    async def plan(body: RetentionPlan, request: Request):
        return await storage.plan(auth.user(request)["id"], body.objectId, body.requestId)

    @router.get("/retention/plans/{identifier}")
    async def inspect(identifier: str, request: Request):
        return await storage.inspect(auth.user(request)["id"], identifier)

    @router.post("/retention/plans/{identifier}/{action}")
    async def transition(identifier: str, action: str, request: Request):
        return await storage.transition(auth.user(request)["id"], identifier, action)

    return router
