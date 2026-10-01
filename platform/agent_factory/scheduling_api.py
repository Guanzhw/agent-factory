"""Owner-scoped, plan-only schedule governance over the native poller."""
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScheduleCreate(Body):
    planId: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=120)
    cron: str = Field(min_length=5, max_length=100)
    timezone: str = Field(default="Etc/UTC", min_length=1, max_length=100)


class ScheduleUpdate(Body):
    cron: str = Field(min_length=5, max_length=100)
    timezone: str = Field(default="Etc/UTC", min_length=1, max_length=100)


class Enabled(Body):
    enabled: bool


class Trigger(Body):
    requestId: str = Field(min_length=8, max_length=100, pattern=r"^[a-zA-Z0-9_.:-]+$")


def scheduling_router(auth, service):
    router = APIRouter(prefix="/api/factory/schedules")

    def owner(request):
        user = auth.user(request)
        auth.require(user["id"], "run")
        return user["id"]

    @router.get("")
    def schedules(request: Request):
        return service.list(owner(request))

    @router.post("", status_code=201)
    def create(body: ScheduleCreate, request: Request):
        return service.create(owner(request), body.planId, body.name, body.cron, body.timezone)

    @router.get("/{schedule_id}")
    def detail(schedule_id: str, request: Request):
        return service.get(owner(request), schedule_id)

    @router.patch("/{schedule_id}")
    def update(schedule_id: str, body: ScheduleUpdate, request: Request):
        return service.update(owner(request), schedule_id, body.cron, body.timezone)

    @router.post("/{schedule_id}/enabled")
    def enable(schedule_id: str, body: Enabled, request: Request):
        return service.set_enabled(owner(request), schedule_id, body.enabled)

    @router.get("/{schedule_id}/occurrences")
    def occurrences(schedule_id: str, request: Request):
        return service.occurrences(owner(request), schedule_id)

    @router.post("/{schedule_id}/trigger", status_code=202)
    async def trigger(schedule_id: str, body: Trigger, request: Request):
        return await service.trigger(owner(request), schedule_id, body.requestId)

    @router.post("/{schedule_id}/occurrences/{occurrence_id}/cancel")
    async def cancel(schedule_id: str, occurrence_id: str, request: Request):
        return await service.cancel_occurrence(owner(request), schedule_id, occurrence_id)

    return router
