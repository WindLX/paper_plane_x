"""Project 路由."""

import logging
import shutil
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, status

from paper_plane_x_backend.api.dependencies import DBDep
from paper_plane_x_backend.config import settings
from paper_plane_x_backend.models import Paper, Project
from paper_plane_x_backend.schemas import (
    MessageResponse,
    PaperDetailResponse,
    PaperListResponse,
    PaperResponse,
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)

router = APIRouter(prefix="/projects", tags=["projects"])
logger = logging.getLogger(__name__)


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
    now = datetime.now()
    project = Project(
        project_id=str(uuid4()),
        name=request.name,
        description=request.description,
        created_at=now,
        updated_at=now,
        operation_logs=[],
    )

    db.insert("projects", project.to_db_dict())
    logger.info(
        "event=project.created project_id=%s name=%s", project.project_id, project.name
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
    # 获取总数
    count_result = db.fetchone("SELECT COUNT(*) as count FROM projects")
    total = count_result["count"] if count_result else 0

    # 获取列表
    rows = db.fetchall(
        """
        SELECT * FROM projects
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    )

    items = [_project_to_response(Project.from_db_row(row)) for row in rows]
    logger.info(
        "event=project.listed offset=%s limit=%s returned=%s total=%s",
        offset,
        limit,
        len(items),
        total,
    )

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
    row = db.fetchone(
        "SELECT * FROM projects WHERE project_id = ?",
        (project_id,),
    )

    if not row:
        logger.warning("event=project.not_found project_id=%s", project_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    project = Project.from_db_row(row)
    logger.debug("event=project.fetched project_id=%s", project_id)
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
    # 检查项目是否存在
    existing = db.fetchone(
        "SELECT * FROM projects WHERE project_id = ?",
        (project_id,),
    )
    if not existing:
        logger.warning("event=project.update_not_found project_id=%s", project_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    # 构建更新数据
    update_data: dict[str, Any] = {"updated_at": datetime.now()}
    if request.name is not None:
        update_data["name"] = request.name
    if request.description is not None:
        update_data["description"] = request.description

    if len(update_data) > 1:  # 除了 updated_at 还有其他字段
        db.update(
            "projects",
            update_data,
            "project_id = ?",
            (project_id,),
        )
        logger.info(
            "event=project.updated project_id=%s fields=%s",
            project_id,
            sorted([k for k in update_data.keys() if k != "updated_at"]),
        )
    else:
        logger.debug(
            "event=project.update_skipped project_id=%s reason=no_mutable_fields",
            project_id,
        )

    # 获取更新后的数据
    row = db.fetchone(
        "SELECT * FROM projects WHERE project_id = ?",
        (project_id,),
    )
    assert row is not None  # 前面已经检查过存在性
    project = Project.from_db_row(row)
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
    # 检查项目是否存在
    existing = db.fetchone(
        "SELECT 1 FROM projects WHERE project_id = ?",
        (project_id,),
    )
    if not existing:
        logger.warning("event=project.delete_not_found project_id=%s", project_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    db.delete(
        "projects",
        "project_id = ?",
        (project_id,),
    )
    logger.info("event=project.deleted project_id=%s", project_id)

    return MessageResponse(message=f"Project {project_id} deleted successfully")


# ==================== Paper Endpoints ====================


def _paper_to_response(paper: Paper) -> PaperResponse:
    """将 Paper 模型转换为响应模型."""
    return PaperResponse(
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
    # 检查项目是否存在
    existing = db.fetchone(
        "SELECT 1 FROM projects WHERE project_id = ?",
        (project_id,),
    )
    if not existing:
        logger.warning("event=paper.list_project_not_found project_id=%s", project_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    # 获取总数
    count_result = db.fetchone(
        "SELECT COUNT(*) as count FROM papers WHERE project_id = ?",
        (project_id,),
    )
    total = count_result["count"] if count_result else 0

    # 获取列表
    rows = db.fetchall(
        """
        SELECT * FROM papers
        WHERE project_id = ?
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (project_id, limit, offset),
    )

    items = [_paper_to_response(Paper.from_db_row(row)) for row in rows]
    logger.info(
        "event=paper.listed project_id=%s offset=%s limit=%s returned=%s total=%s",
        project_id,
        offset,
        limit,
        len(items),
        total,
    )

    return PaperListResponse(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/{project_id}/papers/",
    response_model=PaperListResponse,
    include_in_schema=False,
)
async def list_project_papers_with_trailing_slash(
    project_id: str,
    db: DBDep,
    offset: int = Query(0, ge=0, description="偏移量"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
) -> PaperListResponse:
    """兼容尾斜杠路径，避免客户端收到 307 重定向。"""
    return await list_project_papers(
        project_id=project_id, db=db, offset=offset, limit=limit
    )


@router.get(
    "/{project_id}/papers/{paper_id}",
    response_model=PaperDetailResponse,
    summary="获取论文详情",
    responses={
        404: {"description": "项目或论文不存在"},
    },
)
async def get_paper(
    project_id: str,
    paper_id: str,
    db: DBDep,
) -> PaperDetailResponse:
    """获取论文详情.

    Args:
        project_id: 项目 ID
        paper_id: 论文 ID
        db: 数据库实例

    Returns:
        PaperDetailResponse: 论文详情（包含提取数据）

    Raises:
        HTTPException: 项目或论文不存在时抛出 404
    """
    # 检查项目是否存在
    existing = db.fetchone(
        "SELECT 1 FROM projects WHERE project_id = ?",
        (project_id,),
    )
    if not existing:
        logger.warning("event=paper.get_project_not_found project_id=%s", project_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    # 获取论文
    row = db.fetchone(
        """
        SELECT * FROM papers
        WHERE paper_id = ? AND project_id = ?
        """,
        (paper_id, project_id),
    )

    if not row:
        logger.warning(
            "event=paper.get_not_found project_id=%s paper_id=%s",
            project_id,
            paper_id,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Paper {paper_id} not found in project {project_id}",
        )

    paper = Paper.from_db_row(row)
    logger.debug("event=paper.fetched project_id=%s paper_id=%s", project_id, paper_id)

    return PaperDetailResponse(
        paper_id=paper.paper_id,
        project_id=paper.project_id,
        title=paper.title,
        authors=paper.authors,
        year=paper.year,
        venue=paper.venue,
        doi=paper.doi,
        raw_pdf_path=paper.raw_pdf_path,
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


@router.delete(
    "/{project_id}/papers/{paper_id}",
    response_model=MessageResponse,
    summary="删除论文",
    responses={
        404: {"description": "项目或论文不存在"},
        409: {"description": "论文正在处理中，不能删除"},
    },
)
async def delete_paper(
    project_id: str,
    paper_id: str,
    db: DBDep,
) -> MessageResponse:
    """删除单篇论文记录及其本地文件目录。"""
    project = db.fetchone(
        "SELECT 1 FROM projects WHERE project_id = ?",
        (project_id,),
    )
    if not project:
        logger.warning("event=paper.delete_project_not_found project_id=%s", project_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )

    row = db.fetchone(
        """
        SELECT paper_id, extraction_status, raw_pdf_path
        FROM papers
        WHERE project_id = ? AND paper_id = ?
        """,
        (project_id, paper_id),
    )
    if not row:
        logger.warning(
            "event=paper.delete_not_found project_id=%s paper_id=%s",
            project_id,
            paper_id,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Paper {paper_id} not found in project {project_id}",
        )

    if row["extraction_status"] in {"PENDING", "PROCESSING"}:
        logger.warning(
            "event=paper.delete_blocked project_id=%s paper_id=%s status=%s",
            project_id,
            paper_id,
            row["extraction_status"],
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Paper {paper_id} is being processed and cannot be deleted",
        )

    db.delete(
        "papers",
        "paper_id = ? AND project_id = ?",
        (paper_id, project_id),
    )

    paper_dir = settings.MINERU_OUTPUT_DIR / paper_id
    if paper_dir.exists():
        try:
            shutil.rmtree(paper_dir)
            logger.info(
                "event=paper.artifacts_deleted project_id=%s paper_id=%s path=%s",
                project_id,
                paper_id,
                paper_dir,
            )
        except Exception:
            logger.exception(
                "event=paper.artifacts_delete_failed project_id=%s paper_id=%s path=%s",
                project_id,
                paper_id,
                paper_dir,
            )

    logger.info("event=paper.deleted project_id=%s paper_id=%s", project_id, paper_id)
    return MessageResponse(message=f"Paper {paper_id} deleted successfully")
