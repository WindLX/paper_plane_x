"""Project API 测试."""

import json
from datetime import datetime

from fastapi.testclient import TestClient

from paper_plane_x_backend.services import Database


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
        db.insert(
            "papers",
            {
                "paper_id": "paper-to-delete",
                "project_id": project_id,
                "title": "A Paper",
                "authors": json.dumps(["Alice"], ensure_ascii=False),
                "md_content": "",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "FAILED",
                "fact_check_status": "FAILED",
                "extraction_retry_count": 1,
                "created_at": now,
                "updated_at": now,
            },
        )

        response = client.delete(
            f"/api/v1/projects/{project_id}/papers/paper-to-delete"
        )
        assert response.status_code == 200
        assert "deleted" in response.json()["message"]

        detail_response = client.get(
            f"/api/v1/projects/{project_id}/papers/paper-to-delete"
        )
        assert detail_response.status_code == 404

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
        db.insert(
            "papers",
            {
                "paper_id": "paper-processing",
                "project_id": project_id,
                "title": "Processing Paper",
                "authors": json.dumps(["Bob"], ensure_ascii=False),
                "md_content": "",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "PROCESSING",
                "fact_check_status": "PENDING",
                "extraction_retry_count": 0,
                "created_at": now,
                "updated_at": now,
            },
        )

        response = client.delete(
            f"/api/v1/projects/{project_id}/papers/paper-processing"
        )
        assert response.status_code == 409
