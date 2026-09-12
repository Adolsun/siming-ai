"""Read-only call inspection plus local diagnostic settings and cleanup."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.background import BackgroundTask
from starlette.responses import FileResponse

from ..core.response import ApiResponse
from ..modules.operations.application.trace_capture import owner_id
from ..modules.operations.domain.context_trace import TracePolicyUpdate, TraceQuery
from ..modules.operations.interfaces.trace_dependencies import get_trace_queries

router = APIRouter(prefix="/context-traces", tags=["context-traces"])


def _queries():
    service = get_trace_queries()
    if service is None:
        raise HTTPException(503, "调用记录暂时不可用；正常生成不受影响。")
    return service


def _owner(request: Request) -> str:
    return owner_id(request.scope.get("state", {}))


TraceService = Annotated[Any, Depends(_queries)]


def _require(service, owner: str, trace_id: str) -> dict:
    trace = service.trace(owner, trace_id)
    if not trace:
        raise HTTPException(404, "记录不存在、已过期或不属于当前设备。")
    return trace


@router.get("/settings")
def settings(request: Request, service: TraceService):
    return ApiResponse.success(data=service.store.health(_owner(request)))


@router.put("/settings")
def update_settings(payload: TracePolicyUpdate, request: Request, service: TraceService):
    return ApiResponse.success(
        data=service.store.set_policy(_owner(request), payload.mode, payload.duration_minutes)
    )


@router.post("/search")
def search(payload: TraceQuery, request: Request, service: TraceService):
    return ApiResponse.success(data=service.list_traces(_owner(request), payload))


@router.delete("")
def clear(request: Request, service: TraceService):
    return ApiResponse.success(data={"deleted": service.store.clear(_owner(request))})


@router.get("/{trace_id}")
def detail(trace_id: str, request: Request, service: TraceService):
    return ApiResponse.success(data=_require(service, _owner(request), trace_id))


@router.get("/{trace_id}/events")
def events(
    trace_id: str,
    request: Request,
    service: TraceService,
    after: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
):
    owner = _owner(request)
    _require(service, owner, trace_id)
    return ApiResponse.success(data={"items": service.store.events(owner, trace_id, after, limit)})


@router.get("/{trace_id}/payloads/{payload_id}")
def payload(
    trace_id: str,
    payload_id: str,
    request: Request,
    service: TraceService,
    offset: int = Query(0, ge=0, le=16 * 1024 * 1024),
):
    owner = _owner(request)
    _require(service, owner, trace_id)
    value = service.store.payload(owner, trace_id, payload_id, offset)
    if value is None:
        raise HTTPException(404, "本段内容未记录或已清理。")
    return ApiResponse.success(data=value)


@router.get("/{trace_id}/export")
def export(trace_id: str, request: Request, service: TraceService):
    owner = _owner(request)
    _require(service, owner, trace_id)
    try:
        path = service.export(owner, trace_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return FileResponse(
        path,
        filename=f"siming-trace-{trace_id}.zip",
        media_type="application/zip",
        background=BackgroundTask(path.unlink, missing_ok=True),
    )
