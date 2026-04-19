"""Project API 测试."""

import json
from datetime import datetime

from fastapi.testclient import TestClient

from paper_plane_x_backend.services import Database


def _insert_linked_paper(
    db: Database, project_id: str, payload: dict[str, object]
) -> None:
    data = dict(payload)
    paper_id = data["paper_id"]
    db.insert("papers", data)
    db.execute(
        """
        INSERT INTO paper_projects (paper_id, project_id)
        VALUES (?, ?)
        """,
        (paper_id, project_id),
    )


class TestProjectAPI:
    """Project API 测试类."""

    def test_create_project(self, client: TestClient) -> None:
        """测试创建项目."""
        response = client.post(
            "/api/v1/projects",
            json={"name": "Test Project", "description": "Test Description"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Project"
        assert data["description"] == "Test Description"
        assert "project_id" in data

    def test_create_project_without_description(self, client: TestClient) -> None:
        """测试创建项目（无描述）."""
        response = client.post(
            "/api/v1/projects",
            json={"name": "Test Project 2"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Project 2"
        assert data["description"] is None

    def test_create_project_validation_error(self, client: TestClient) -> None:
        """测试创建项目参数验证失败."""
        # 空名称
        response = client.post(
            "/api/v1/projects",
            json={"name": ""},
        )
        assert response.status_code == 422

    def test_get_project(self, client: TestClient) -> None:
        """测试获取项目详情."""
        # 先创建项目
        create_response = client.post(
            "/api/v1/projects",
            json={"name": "Get Test", "description": "Get Description"},
        )
        project_id = create_response.json()["project_id"]

        # 获取项目
        response = client.get(f"/api/v1/projects/{project_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["project_id"] == project_id
        assert data["name"] == "Get Test"

    def test_get_project_not_found(self, client: TestClient) -> None:
        """测试获取不存在的项目."""
        response = client.get("/api/v1/projects/non-existent-id")
        assert response.status_code == 404

    def test_list_projects(self, client: TestClient) -> None:
        """测试列出项目."""
        # 创建多个项目
        for i in range(3):
            client.post(
                "/api/v1/projects",
                json={"name": f"List Test {i}", "description": f"Desc {i}"},
            )

        # 获取列表
        response = client.get("/api/v1/projects?offset=0&limit=2")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert data["offset"] == 0
        assert data["limit"] == 2
        assert len(data["items"]) <= 2

    def test_update_project(self, client: TestClient) -> None:
        """测试更新项目."""
        # 先创建项目
        create_response = client.post(
            "/api/v1/projects",
            json={"name": "Update Test", "description": "Original Desc"},
        )
        project_id = create_response.json()["project_id"]

        # 更新项目
        response = client.patch(
            f"/api/v1/projects/{project_id}",
            json={"name": "Updated Name", "description": "Updated Desc"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Name"
        assert data["description"] == "Updated Desc"

    def test_update_project_partial(self, client: TestClient) -> None:
        """测试部分更新项目."""
        # 先创建项目
        create_response = client.post(
            "/api/v1/projects",
            json={"name": "Partial Update Test", "description": "Keep Desc"},
        )
        project_id = create_response.json()["project_id"]

        # 只更新名称
        response = client.patch(
            f"/api/v1/projects/{project_id}",
            json={"name": "Only Name Updated"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Only Name Updated"
        assert data["description"] == "Keep Desc"

    def test_update_project_not_found(self, client: TestClient) -> None:
        """测试更新不存在的项目."""
        response = client.patch(
            "/api/v1/projects/non-existent-id",
            json={"name": "New Name"},
        )
        assert response.status_code == 404

    def test_delete_project(self, client: TestClient) -> None:
        """测试删除项目."""
        # 先创建项目
        create_response = client.post(
            "/api/v1/projects",
            json={"name": "Delete Test"},
        )
        project_id = create_response.json()["project_id"]

        # 删除项目
        response = client.delete(f"/api/v1/projects/{project_id}")
        assert response.status_code == 200
        data = response.json()
        assert "deleted" in data["message"]

        # 确认已删除
        get_response = client.get(f"/api/v1/projects/{project_id}")
        assert get_response.status_code == 404

    def test_delete_project_not_found(self, client: TestClient) -> None:
        """测试删除不存在的项目."""
        response = client.delete("/api/v1/projects/non-existent-id")
        assert response.status_code == 404

    def test_delete_paper(self, client: TestClient, db: Database) -> None:
        """测试删除单篇论文."""
        create_response = client.post(
            "/api/v1/projects",
            json={"name": "Paper Delete Project"},
        )
        project_id = create_response.json()["project_id"]

        now = datetime.now()
        _insert_linked_paper(
            db,
            project_id,
            {
                "paper_id": "paper-to-delete",
                "title": "A Paper",
                "authors": json.dumps(["Alice"], ensure_ascii=False),
                "md_content": "",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "FAILED",
                "extraction_fact_check_status": "FAILED",
                "extraction_retry_count": 1,
                "created_at": now,
                "updated_at": now,
            },
        )

        response = client.delete(
            f"/api/v1/projects/{project_id}/papers/paper-to-delete"
        )
        assert response.status_code == 200
        assert "unlinked" in response.json()["message"]

        detail_response = client.get(
            f"/api/v1/projects/{project_id}/papers/paper-to-delete"
        )
        assert detail_response.status_code == 405

    def test_delete_paper_not_found(self, client: TestClient) -> None:
        """测试删除不存在的论文."""
        create_response = client.post(
            "/api/v1/projects",
            json={"name": "Paper Delete 404 Project"},
        )
        project_id = create_response.json()["project_id"]

        response = client.delete(f"/api/v1/projects/{project_id}/papers/non-existent")
        assert response.status_code == 404

    def test_delete_paper_conflict_when_processing(
        self, client: TestClient, db: Database
    ) -> None:
        """测试处理中论文不可删除."""
        create_response = client.post(
            "/api/v1/projects",
            json={"name": "Paper Delete Conflict Project"},
        )
        project_id = create_response.json()["project_id"]

        now = datetime.now()
        _insert_linked_paper(
            db,
            project_id,
            {
                "paper_id": "paper-processing",
                "title": "Processing Paper",
                "authors": json.dumps(["Bob"], ensure_ascii=False),
                "md_content": "",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "PROCESSING",
                "extraction_fact_check_status": "PENDING",
                "extraction_retry_count": 0,
                "created_at": now,
                "updated_at": now,
            },
        )

        response = client.delete(
            f"/api/v1/projects/{project_id}/papers/paper-processing"
        )
        assert response.status_code == 200

    def test_project_search_delegates_to_librarian_with_project_scope(
        self, client: TestClient, db: Database
    ) -> None:
        """测试 project search 会强制使用路径中的 project_id 进行作用域搜索。"""
        p1_resp = client.post(
            "/api/v1/projects",
            json={"name": "Project Search P1"},
        )
        p2_resp = client.post(
            "/api/v1/projects",
            json={"name": "Project Search P2"},
        )
        p1 = p1_resp.json()["project_id"]
        p2 = p2_resp.json()["project_id"]

        now = datetime.now()
        _insert_linked_paper(
            db,
            p1,
            {
                "paper_id": "paper-search-in-p1",
                "title": "P1 Paper",
                "authors": json.dumps(["Alice"], ensure_ascii=False),
                "year": 2024,
                "md_content": "Lyapunov stability design",
                "images_paths": json.dumps([], ensure_ascii=False),
                "quick_scan": json.dumps({"verdict": "推荐精读"}, ensure_ascii=False),
                "extraction_status": "COMPLETED",
                "extraction_fact_check_status": "PASSED",
                "analysis_fact_check_status": "PASSED",
                "created_at": now,
                "updated_at": now,
            },
        )
        _insert_linked_paper(
            db,
            p2,
            {
                "paper_id": "paper-search-in-p2",
                "title": "P2 Paper",
                "authors": json.dumps(["Bob"], ensure_ascii=False),
                "year": 2024,
                "md_content": "Lyapunov stability design",
                "images_paths": json.dumps([], ensure_ascii=False),
                "quick_scan": json.dumps({"verdict": "推荐精读"}, ensure_ascii=False),
                "extraction_status": "COMPLETED",
                "extraction_fact_check_status": "PASSED",
                "analysis_fact_check_status": "PASSED",
                "created_at": now,
                "updated_at": now,
            },
        )

        response = client.post(
            f"/api/v1/projects/{p1}/search",
            json={
                "project_id": p2,
                "condition_group": {
                    "logic": "and",
                    "predicates": [
                        {
                            "field": "md_content",
                            "op": "contains",
                            "value": "lyapunov",
                        }
                    ],
                    "groups": [],
                },
                "limit": 10,
                "offset": 0,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["project_id"] == p1
        assert payload["total"] == 1
        assert payload["paper_ids"] == ["paper-search-in-p1"]
