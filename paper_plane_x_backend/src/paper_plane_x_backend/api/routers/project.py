"""Project 路由."""

import logging
from typing import NoReturn

from fastapi import APIRouter, HTTPException, Query, status

from paper_plane_x_backend.api.dependencies import DBDep
from paper_plane_x_backend.api.routers.librarian import run_search_paper
from paper_plane_x_backend.models import Paper, Project
from paper_plane_x_backend.schemas import (
    LibrarianUnifiedSearchRequest,
    LibrarianUnifiedSearchResponse,
    MessageResponse,
    PaperListResponse,
    PaperResponse,
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)
from paper_plane_x_backend.services.orchestrators.project import (
    ProjectDomainError,
    ProjectOrchestrator,
)

router = APIRouter(prefix="/projects", tags=["projects"])
logger = logging.getLogger(__name__)


def _build_orchestrator(db: DBDep) -> ProjectOrchestrator:
    return ProjectOrchestrator(db=db)


def _raise_as_http(exc: ProjectDomainError) -> NoReturn:
    logger.warning(
        "event=project.domain_error status=%s detail=%s",
        exc.status_code,
        exc.detail,
    )
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


def _project_to_response(project: Project) -> ProjectResponse:
    """将 Project 模型转换为响应模型."""
    return ProjectResponse(
        project_id=project.project_id,
        name=project.name,
        description=project.description,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建项目",
)
async def create_project(
    request: ProjectCreateRequest,
    db: DBDep,
) -> ProjectResponse:
    """创建新项目.

    Args:
        request: 创建项目请求
        db: 数据库实例

    Returns:
        ProjectResponse: 创建的项目
    """
    orchestrator = _build_orchestrator(db)
    project = orchestrator.create_project(
        name=request.name,
        description=request.description,
    )
    return _project_to_response(project)


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="列出项目",
)
async def list_projects(
    db: DBDep,
    offset: int = Query(0, ge=0, description="偏移量"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
) -> ProjectListResponse:
    """获取项目列表.

    Args:
        db: 数据库实例
        offset: 分页偏移量
        limit: 每页数量

    Returns:
        ProjectListResponse: 项目列表响应
    """
    orchestrator = _build_orchestrator(db)
    projects, total = orchestrator.list_projects(offset=offset, limit=limit)
    items = [_project_to_response(project) for project in projects]

    return ProjectListResponse(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="获取项目详情",
    responses={
        404: {"description": "项目不存在"},
    },
)
async def get_project(
    project_id: str,
    db: DBDep,
) -> ProjectResponse:
    """获取单个项目详情.

    Args:
        project_id: 项目 ID
        db: 数据库实例

    Returns:
        ProjectResponse: 项目详情

    Raises:
        HTTPException: 项目不存在时抛出 404
    """
    orchestrator = _build_orchestrator(db)
    try:
        project = orchestrator.get_project(project_id)
    except ProjectDomainError as exc:
        _raise_as_http(exc)

    return _project_to_response(project)


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="更新项目",
    responses={
        404: {"description": "项目不存在"},
    },
)
async def update_project(
    project_id: str,
    request: ProjectUpdateRequest,
    db: DBDep,
) -> ProjectResponse:
    """更新项目信息.

    Args:
        project_id: 项目 ID
        request: 更新请求
        db: 数据库实例

    Returns:
        ProjectResponse: 更新后的项目

    Raises:
        HTTPException: 项目不存在时抛出 404
    """
    orchestrator = _build_orchestrator(db)
    try:
        project = orchestrator.update_project(
            project_id=project_id,
            name=request.name,
            description=request.description,
        )
    except ProjectDomainError as exc:
        _raise_as_http(exc)

    return _project_to_response(project)


@router.delete(
    "/{project_id}",
    response_model=MessageResponse,
    summary="删除项目",
    responses={
        404: {"description": "项目不存在"},
    },
)
async def delete_project(
    project_id: str,
    db: DBDep,
) -> MessageResponse:
    """删除项目.

    Args:
        project_id: 项目 ID
        db: 数据库实例

    Returns:
        MessageResponse: 删除成功消息

    Raises:
        HTTPException: 项目不存在时抛出 404
    """
    orchestrator = _build_orchestrator(db)
    try:
        orchestrator.delete_project(project_id)
    except ProjectDomainError as exc:
        _raise_as_http(exc)

    return MessageResponse(message=f"Project {project_id} deleted successfully")


# ==================== Paper Endpoints ====================


def _paper_to_response(
    orchestrator: ProjectOrchestrator,
    paper: Paper,
) -> PaperResponse:
    """将 Paper 模型转换为响应模型."""
    return PaperResponse(
        paper_id=paper.paper_id,
        project_ids=orchestrator.list_paper_project_ids(paper.paper_id),
        title=paper.title,
        authors=paper.authors,
        year=paper.year,
        publication=paper.publication,
        doi=paper.doi,
        custom_meta=paper.custom_meta,
        raw_pdf_path=paper.raw_pdf_path,
        raw_pdf_sha256=paper.raw_pdf_sha256,
        extraction_status=paper.extraction_status,
        extraction_fact_check_status=paper.extraction_fact_check_status,
        analysis_fact_check_status=paper.analysis_fact_check_status,
        extraction_retry_count=paper.extraction_retry_count,
        analysis_retry_count=paper.analysis_retry_count,
        created_at=paper.created_at,
        updated_at=paper.updated_at,
    )


@router.get(
    "/{project_id}/papers",
    response_model=PaperListResponse,
    summary="列出项目论文",
    responses={
        404: {"description": "项目不存在"},
    },
)
async def list_project_papers(
    project_id: str,
    db: DBDep,
    offset: int = Query(0, ge=0, description="偏移量"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
) -> PaperListResponse:
    """获取项目的论文列表.

    Args:
        project_id: 项目 ID
        db: 数据库实例
        offset: 分页偏移量
        limit: 每页数量

    Returns:
        PaperListResponse: 论文列表响应

    Raises:
        HTTPException: 项目不存在时抛出 404
    """
    orchestrator = _build_orchestrator(db)
    try:
        papers, total = orchestrator.list_papers(
            project_id=project_id,
            offset=offset,
            limit=limit,
        )
    except ProjectDomainError as exc:
        _raise_as_http(exc)

    items = [
        _paper_to_response(orchestrator=orchestrator, paper=paper) for paper in papers
    ]

    return PaperListResponse(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/{project_id}/papers/{paper_id}",
    response_model=MessageResponse,
    summary="将论文关联到项目",
    responses={404: {"description": "项目或论文不存在"}},
)
async def link_paper(
    project_id: str,
    paper_id: str,
    db: DBDep,
) -> MessageResponse:
    orchestrator = _build_orchestrator(db)
    try:
        orchestrator.link_paper(project_id=project_id, paper_id=paper_id)
    except ProjectDomainError as exc:
        _raise_as_http(exc)
    return MessageResponse(message=f"Paper {paper_id} linked to project {project_id}")


@router.delete(
    "/{project_id}/papers/{paper_id}",
    response_model=MessageResponse,
    summary="从项目中移除论文关联",
    responses={
        404: {"description": "项目或论文不存在"},
    },
)
async def unlink_paper(
    project_id: str,
    paper_id: str,
    db: DBDep,
) -> MessageResponse:
    """从项目中移除论文关联，不删除论文实体。"""
    orchestrator = _build_orchestrator(db)
    try:
        orchestrator.unlink_paper(project_id=project_id, paper_id=paper_id)
    except ProjectDomainError as exc:
        _raise_as_http(exc)

    return MessageResponse(
        message=f"Paper {paper_id} unlinked from project {project_id}"
    )


@router.post(
    "/{project_id}/search",
    response_model=LibrarianUnifiedSearchResponse,
    summary="Project 作用域统一搜索",
    responses={
        404: {"description": "项目不存在"},
    },
)
async def search_project(
    project_id: str,
    request: LibrarianUnifiedSearchRequest,
    db: DBDep,
) -> LibrarianUnifiedSearchResponse:
    orchestrator = _build_orchestrator(db)
    try:
        orchestrator.get_project(project_id)
    except ProjectDomainError as exc:
        _raise_as_http(exc)

    scoped_request = request.model_copy(update={"project_id": project_id})
    return run_search_paper(request=scoped_request, db=db)
