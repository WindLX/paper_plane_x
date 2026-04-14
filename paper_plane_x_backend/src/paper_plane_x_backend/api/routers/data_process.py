"""Data Process 路由.

职责：
- 解析 HTTP 请求
- 参数校验
- 将业务编排委托给 Orchestrator
"""

import logging
from typing import NoReturn

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from paper_plane_x_backend.api.dependencies import DBDep
from paper_plane_x_backend.config import settings
from paper_plane_x_backend.models import DataProcessTaskStatus, Paper
from paper_plane_x_backend.schemas import (
    DataProcessManualUpdateRequest,
    DataProcessSubmitResponse,
    DataProcessTaskListResponse,
    DataProcessTaskResponse,
    PaperDetailResponse,
)
from paper_plane_x_backend.services.data_process_orchestrator import (
    DataProcessDomainError,
    DataProcessOrchestrator,
)
from paper_plane_x_backend.services.data_process_task_manager import (
    DataProcessTaskManager,
    DataProcessTaskState,
)

router = APIRouter(prefix="/projects", tags=["data-process"])
logger = logging.getLogger(__name__)

_task_manager = DataProcessTaskManager(
    worker_count=settings.DATA_PROCESS_WORKER_COUNT,
    shutdown_timeout=settings.DATA_PROCESS_SHUTDOWN_TIMEOUT,
)


def _build_orchestrator(db: DBDep) -> DataProcessOrchestrator:
    return DataProcessOrchestrator(db=db, task_manager=_task_manager)


def _raise_as_http(exc: DataProcessDomainError) -> NoReturn:
    logger.warning(
        "event=data_process.domain_error status=%s detail=%s",
        exc.status_code,
        exc.detail,
    )
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


def _to_task_response(state: DataProcessTaskState) -> DataProcessTaskResponse:
    paper_id = state.payload.get("paper_id")
    if not isinstance(paper_id, str):
        paper_id = ""
    return DataProcessTaskResponse(
        task_id=state.task_id,
        project_id=state.project_id,
        paper_id=paper_id,
        status=state.status,
        created_at=state.created_at,
        started_at=state.started_at,
        finished_at=state.finished_at,
        error=state.error,
        retry_of_task_id=state.retry_of_task_id,
    )


def _to_submit_response(
    *,
    project_id: str,
    task_id: str,
    message: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> DataProcessSubmitResponse:
    return DataProcessSubmitResponse(
        project_id=project_id,
        task_id=task_id,
        status=DataProcessTaskStatus.QUEUED,
        message=message,
        resource_type=resource_type,
        resource_id=resource_id,
    )


def _to_paper_detail_response(paper: Paper) -> PaperDetailResponse:
    return PaperDetailResponse(
        paper_id=paper.paper_id,
        project_id=paper.project_id,
        title=paper.title,
        authors=paper.authors,
        year=paper.year,
        venue=paper.venue,
        doi=paper.doi,
        raw_pdf_path=paper.raw_pdf_path,
        raw_pdf_sha256=paper.raw_pdf_sha256,
        final_fact_check_trace_id=paper.final_fact_check_trace_id,
        extraction_status=paper.extraction_status,
        fact_check_status=paper.fact_check_status,
        extraction_retry_count=paper.extraction_retry_count,
        created_at=paper.created_at,
        updated_at=paper.updated_at,
        quick_scan=paper.quick_scan,
        synthesis_data=paper.synthesis_data,
        fact_check_result=paper.fact_check_result,
    )


async def start_worker_pool() -> None:
    """启动 data-process worker 池。"""
    logger.info("event=data_process.worker_pool_starting")
    await _task_manager.start()


async def stop_worker_pool() -> None:
    """停止 data-process worker 池。"""
    logger.info("event=data_process.worker_pool_stopping")
    await _task_manager.stop()


@router.post(
    "/{project_id}/data-process",
    response_model=DataProcessSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="启动数据处理任务",
)
async def start_data_process(
    project_id: str,
    db: DBDep,
    pdf_file: UploadFile = File(..., description="上传的原始 PDF 文件"),
    title: str | None = Form(default=None, description="论文标题"),
    authors: str | None = Form(default=None, description="作者列表，逗号分隔"),
    year: int | None = Form(default=None, description="发表年份"),
    venue: str | None = Form(default=None, description="发表 venue"),
    doi: str | None = Form(default=None, description="DOI"),
) -> DataProcessSubmitResponse:
    logger.info(
        "event=data_process.start_request_received project_id=%s filename=%s",
        project_id,
        pdf_file.filename,
    )
    orchestrator = _build_orchestrator(db)
    metadata = orchestrator.build_metadata(
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
    )

    try:
        task_state, paper_id = await orchestrator.start(
            project_id=project_id,
            upload_file=pdf_file,
            metadata=metadata,
        )
        return _to_submit_response(
            project_id=project_id,
            task_id=task_state.task_id,
            message="Data-process task queued",
            resource_type="paper",
            resource_id=paper_id,
        )
    except DataProcessDomainError as exc:
        _raise_as_http(exc)


@router.post(
    "/{project_id}/data-process/{paper_id}/retry",
    response_model=DataProcessSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="重试处理已存在论文（覆盖同 ID 上传）",
)
async def retry_data_process(
    project_id: str,
    paper_id: str,
    db: DBDep,
    pdf_file: UploadFile = File(..., description="重新上传的原始 PDF 文件"),
) -> DataProcessSubmitResponse:
    logger.info(
        "event=data_process.retry_upload_request_received project_id=%s paper_id=%s filename=%s",
        project_id,
        paper_id,
        pdf_file.filename,
    )
    orchestrator = _build_orchestrator(db)

    try:
        task_state = await orchestrator.retry_upload(
            project_id=project_id,
            paper_id=paper_id,
            upload_file=pdf_file,
        )
        return _to_submit_response(
            project_id=project_id,
            task_id=task_state.task_id,
            message="Data-process task queued",
            resource_type="paper",
            resource_id=paper_id,
        )
    except DataProcessDomainError as exc:
        _raise_as_http(exc)


@router.patch(
    "/{project_id}/data-process/{paper_id}/manual-update",
    response_model=PaperDetailResponse,
    summary="人工更新论文元数据与处理结果",
    responses={
        404: {"description": "项目或论文不存在"},
        422: {"description": "请求参数校验失败"},
    },
)
async def manual_update_data_process_result(
    project_id: str,
    paper_id: str,
    request: DataProcessManualUpdateRequest,
    db: DBDep,
) -> PaperDetailResponse:
    logger.info(
        "event=data_process.manual_update_request_received project_id=%s paper_id=%s",
        project_id,
        paper_id,
    )
    orchestrator = _build_orchestrator(db)
    try:
        updated_paper = orchestrator.manual_update_paper(
            project_id=project_id,
            paper_id=paper_id,
            title=request.title,
            authors=request.authors,
            year=request.year,
            venue=request.venue,
            doi=request.doi,
            extraction_status=request.extraction_status,
            quick_scan=request.quick_scan,
            synthesis_data=request.synthesis_data,
            fact_check_status=request.fact_check_status,
            fact_check_result=request.fact_check_result,
        )
    except DataProcessDomainError as exc:
        _raise_as_http(exc)

    return _to_paper_detail_response(updated_paper)


@router.get(
    "/{project_id}/data-process/tasks",
    response_model=DataProcessTaskListResponse,
    summary="查看 data-process 任务队列状态",
)
async def list_data_process_tasks(
    project_id: str, db: DBDep
) -> DataProcessTaskListResponse:
    logger.debug(
        "event=data_process.tasks_list_request_received project_id=%s", project_id
    )
    orchestrator = _build_orchestrator(db)
    try:
        states, counts = orchestrator.list_tasks(project_id)
    except DataProcessDomainError as exc:
        _raise_as_http(exc)

    items = [_to_task_response(state) for state in states]

    return DataProcessTaskListResponse(
        project_id=project_id,
        queued=counts["queued"],
        running=counts["running"],
        completed=counts["completed"],
        failed=counts["failed"],
        canceled=counts["canceled"],
        items=items,
    )


@router.post(
    "/{project_id}/data-process/tasks/{task_id}/cancel",
    response_model=DataProcessTaskResponse,
    summary="终止 data-process 任务",
    responses={
        404: {"description": "项目或任务不存在"},
        409: {"description": "任务已结束"},
    },
)
async def cancel_data_process_task(
    project_id: str,
    task_id: str,
    db: DBDep,
) -> DataProcessTaskResponse:
    logger.info(
        "event=data_process.cancel_request_received project_id=%s task_id=%s",
        project_id,
        task_id,
    )
    orchestrator = _build_orchestrator(db)
    try:
        updated = orchestrator.cancel(project_id, task_id)
    except DataProcessDomainError as exc:
        _raise_as_http(exc)

    return _to_task_response(updated)


@router.post(
    "/{project_id}/data-process/tasks/{task_id}/retry",
    response_model=DataProcessSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="重试失败或已取消任务",
    responses={
        404: {"description": "项目或任务不存在"},
        409: {"description": "任务状态不允许重试"},
        400: {"description": "缺少可重试的原始 PDF"},
    },
)
async def retry_failed_task(
    project_id: str,
    task_id: str,
    db: DBDep,
) -> DataProcessSubmitResponse:
    logger.info(
        "event=data_process.retry_task_request_received project_id=%s task_id=%s",
        project_id,
        task_id,
    )
    orchestrator = _build_orchestrator(db)
    try:
        task_state, paper_id = await orchestrator.retry_failed_task(
            project_id=project_id,
            task_id=task_id,
        )
    except DataProcessDomainError as exc:
        _raise_as_http(exc)

    return _to_submit_response(
        project_id=project_id,
        task_id=task_state.task_id,
        message="Data-process task queued",
        resource_type="paper",
        resource_id=paper_id,
    )
