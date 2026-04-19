"""API 请求/响应模型.

定义 REST API 的输入输出数据结构。
"""

from paper_plane_x_backend.schemas.api.common import ErrorResponse, MessageResponse
from paper_plane_x_backend.schemas.api.data_process import (
    DataProcessManualUpdateRequest,
    DataProcessRequest,
    DataProcessSubmitResponse,
    DataProcessTaskListResponse,
    DataProcessTaskResponse,
)
from paper_plane_x_backend.schemas.api.librarian import (
    LibrarianConditionGroup,
    LibrarianConditionPredicate,
    LibrarianMatrixRequest,
    LibrarianMatrixResponse,
    LibrarianProjectionRequest,
    LibrarianProjectionResponse,
    LibrarianUnifiedSearchRequest,
    LibrarianUnifiedSearchResponse,
)
from paper_plane_x_backend.schemas.api.paper import (
    PaperDetailResponse,
    PaperListResponse,
    PaperResponse,
)
from paper_plane_x_backend.schemas.api.project import (
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)

__all__ = [
    "DataProcessManualUpdateRequest",
    "DataProcessRequest",
    "DataProcessSubmitResponse",
    "DataProcessTaskListResponse",
    "DataProcessTaskResponse",
    "ErrorResponse",
    "LibrarianConditionGroup",
    "LibrarianConditionPredicate",
    "LibrarianMatrixRequest",
    "LibrarianMatrixResponse",
    "LibrarianProjectionRequest",
    "LibrarianProjectionResponse",
    "LibrarianUnifiedSearchRequest",
    "LibrarianUnifiedSearchResponse",
    "MessageResponse",
    "PaperDetailResponse",
    "PaperListResponse",
    "PaperResponse",
    "ProjectCreateRequest",
    "ProjectListResponse",
    "ProjectResponse",
    "ProjectUpdateRequest",
]
