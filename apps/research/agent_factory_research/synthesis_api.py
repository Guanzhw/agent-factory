"""Owner-selected source inputs; execution stays in the existing composition API."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field


class SnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sourceTaskId: str = Field(min_length=1, max_length=128)
    sourceIds: list[str] = Field(min_length=1, max_length=3)
    question: str = Field(min_length=2, max_length=1000)
    expectedFingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    requestId: str = Field(min_length=1, max_length=200)


def synthesis_router(auth, service, settings):
    router = APIRouter(prefix="/api/factory/synthesis")

    def owner(request):
        actor = auth.user(request)["id"]
        if not settings.source_synthesis_enabled:
            raise HTTPException(409, "SYNTHESIS_NOT_CONFIGURED: controlled source synthesis is not enabled")
        return actor

    @router.get("/sources/{task_id}")
    def preview(task_id: str, request: Request):
        return service.preview(owner(request), task_id)

    @router.post("/snapshots", status_code=201)
    def create(body: SnapshotRequest, request: Request):
        return service.create(owner(request), source_task_id=body.sourceTaskId, source_ids=body.sourceIds,
            question=body.question, expected_fingerprint=body.expectedFingerprint, request_id=body.requestId)

    @router.get("/snapshots")
    def history(request: Request, sourceTaskId: str | None = None, after: str | None = None, limit: int = 20):
        return service.list(owner(request), source_task_id=sourceTaskId, after_id=after, limit=limit)

    @router.get("/snapshots/{identifier}")
    def inspect(identifier: str, request: Request):
        return service.read(owner(request), identifier)

    @router.get("/snapshots/{identifier}/current")
    def current(identifier: str, request: Request):
        return service.revalidate(owner(request), identifier)

    return router
