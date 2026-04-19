"""Librarian API 集成测试。"""

import json
from datetime import datetime

from fastapi.testclient import TestClient

from paper_plane_x_backend.services import Database


def _insert_paper(db: Database, paper_id: str) -> None:
    now = datetime.now()
    db.insert(
        "papers",
        {
            "paper_id": paper_id,
            "title": f"Title {paper_id}",
            "authors": json.dumps(["Alice", "Bob"], ensure_ascii=False),
            "custom_meta": json.dumps(
                {"source": {"name": "manual", "version": 2}, "tags": ["x", "y"]},
                ensure_ascii=False,
            ),
            "quick_scan": json.dumps(
                {"verdict": "include", "reason": "fit"}, ensure_ascii=False
            ),
            "synthesis_data": json.dumps(
                {"review_summary": f"summary-{paper_id}"}, ensure_ascii=False
            ),
            "md_content": "",
            "images_paths": json.dumps([], ensure_ascii=False),
            "extraction_status": "COMPLETED",
            "extraction_fact_check_status": "PASSED",
            "analysis_fact_check_status": "PASSED",
            "extraction_retry_count": 0,
            "analysis_retry_count": 0,
            "created_at": now,
            "updated_at": now,
        },
    )


class TestLibrarianAPI:
    """Librarian Layer1 API 测试。"""

    def test_projection_endpoint_returns_value(
        self, client: TestClient, db: Database
    ) -> None:
        _insert_paper(db, "paper-proj-1")

        response = client.post(
            "/api/v1/librarian/projection",
            json={"paper_id": "paper-proj-1", "field_path": "quick_scan.verdict"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["paper_id"] == "paper-proj-1"
        assert payload["field_path"] == "quick_scan.verdict"
        assert payload["value"] == "include"

    def test_matrix_endpoint_returns_items(
        self, client: TestClient, db: Database
    ) -> None:
        _insert_paper(db, "paper-mx-1")
        _insert_paper(db, "paper-mx-2")

        response = client.post(
            "/api/v1/librarian/matrix",
            json={
                "paper_ids": ["paper-mx-1", "paper-mx-2"],
                "field_paths": ["meta.title", "synthesis_data.review_summary"],
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["paper_ids"] == ["paper-mx-1", "paper-mx-2"]
        assert payload["field_paths"] == ["meta.title", "synthesis_data.review_summary"]
        assert payload["items"]["paper-mx-1"]["meta.title"] == "Title paper-mx-1"
        assert (
            payload["items"]["paper-mx-2"]["synthesis_data.review_summary"]
            == "summary-paper-mx-2"
        )

    def test_projection_invalid_root_returns_400(
        self, client: TestClient, db: Database
    ) -> None:
        _insert_paper(db, "paper-proj-2")

        response = client.post(
            "/api/v1/librarian/projection",
            json={"paper_id": "paper-proj-2", "field_path": "badroot.x"},
        )

        assert response.status_code == 400

    def test_projection_custom_meta_deep_path(
        self, client: TestClient, db: Database
    ) -> None:
        _insert_paper(db, "paper-proj-3")

        response = client.post(
            "/api/v1/librarian/projection",
            json={"paper_id": "paper-proj-3", "field_path": "custom_meta.source.name"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["value"] == "manual"

    def test_matrix_custom_meta_deep_path(
        self, client: TestClient, db: Database
    ) -> None:
        _insert_paper(db, "paper-mx-3")
        _insert_paper(db, "paper-mx-4")

        response = client.post(
            "/api/v1/librarian/matrix",
            json={
                "paper_ids": ["paper-mx-3", "paper-mx-4"],
                "field_paths": ["custom_meta.source.name", "custom_meta.tags.1"],
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["items"]["paper-mx-3"]["custom_meta.source.name"] == "manual"
        assert payload["items"]["paper-mx-4"]["custom_meta.tags.1"] == "y"

    def test_matrix_invalid_root_returns_400(
        self, client: TestClient, db: Database
    ) -> None:
        _insert_paper(db, "paper-mx-err")

        response = client.post(
            "/api/v1/librarian/matrix",
            json={
                "paper_ids": ["paper-mx-err"],
                "field_paths": ["badroot.x"],
            },
        )

        assert response.status_code == 400

    def test_projection_keeps_citations(self, client: TestClient, db: Database) -> None:
        _insert_paper(db, "paper-proj-cite-1")
        db.update(
            table="papers",
            data={
                "synthesis_data": json.dumps(
                    {
                        "methodology": {
                            "innovation": {
                                "text": "核心创新",
                                "citations": [{"quote": "q1", "anchor": "#1"}],
                            }
                        }
                    },
                    ensure_ascii=False,
                )
            },
            where="paper_id = ?",
            where_params=("paper-proj-cite-1",),
        )

        response = client.post(
            "/api/v1/librarian/projection",
            json={
                "paper_id": "paper-proj-cite-1",
                "field_path": "synthesis_data.methodology.innovation",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["value"]["text"] == "核心创新"
        assert "citations" in payload["value"]

    def test_matrix_keeps_citations(self, client: TestClient, db: Database) -> None:
        _insert_paper(db, "paper-mx-cite-1")
        db.update(
            table="papers",
            data={
                "analysis_report": json.dumps(
                    {
                        "core_formulation": {
                            "objective_function": {
                                "text": "目标函数",
                                "citations": [{"quote": "q2", "anchor": "#2"}],
                            }
                        }
                    },
                    ensure_ascii=False,
                )
            },
            where="paper_id = ?",
            where_params=("paper-mx-cite-1",),
        )

        response = client.post(
            "/api/v1/librarian/matrix",
            json={
                "paper_ids": ["paper-mx-cite-1"],
                "field_paths": ["analysis_report.core_formulation.objective_function"],
            },
        )

        assert response.status_code == 200
        payload = response.json()
        value = payload["items"]["paper-mx-cite-1"][
            "analysis_report.core_formulation.objective_function"
        ]
        assert value["text"] == "目标函数"
        assert "citations" in value

    def test_search_endpoint_filters_by_condition_group(
        self, client: TestClient, db: Database
    ) -> None:
        _insert_paper(db, "paper-search-1")
        _insert_paper(db, "paper-search-2")
        db.update(
            table="papers",
            data={
                "year": 2024,
                "quick_scan": json.dumps(
                    {"verdict": "推荐精读", "reason": "fit"},
                    ensure_ascii=False,
                ),
            },
            where="paper_id = ?",
            where_params=("paper-search-1",),
        )
        db.update(
            table="papers",
            data={
                "year": 2021,
                "quick_scan": json.dumps(
                    {"verdict": "跳过", "reason": "low fit"},
                    ensure_ascii=False,
                ),
            },
            where="paper_id = ?",
            where_params=("paper-search-2",),
        )

        response = client.post(
            "/api/v1/librarian/search",
            json={
                "condition_group": {
                    "logic": "and",
                    "predicates": [
                        {"field": "meta.year", "op": "between", "value": [2023, 2025]},
                        {
                            "field": "quick_scan.verdict",
                            "op": "contains",
                            "value": "推荐",
                        },
                    ],
                    "groups": [],
                },
                "limit": 10,
                "offset": 0,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert payload["paper_ids"] == ["paper-search-1"]

    def test_search_endpoint_auto_filters_unqualified_status(
        self, client: TestClient, db: Database
    ) -> None:
        _insert_paper(db, "paper-status-pass")
        _insert_paper(db, "paper-status-fail")
        db.update(
            table="papers",
            data={
                "md_content": "Lyapunov design",
            },
            where="paper_id = ?",
            where_params=("paper-status-pass",),
        )
        db.update(
            table="papers",
            data={
                "md_content": "Lyapunov design",
                "extraction_status": "FAILED",
            },
            where="paper_id = ?",
            where_params=("paper-status-fail",),
        )

        response = client.post(
            "/api/v1/librarian/search",
            json={
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
        assert payload["total"] == 1
        assert payload["paper_ids"] == ["paper-status-pass"]

    def test_search_endpoint_supports_nested_condition_group(
        self, client: TestClient, db: Database
    ) -> None:
        _insert_paper(db, "paper-search-n1")
        _insert_paper(db, "paper-search-n2")
        db.update(
            table="papers",
            data={
                "year": 2024,
                "quick_scan": json.dumps({"verdict": "推荐精读"}, ensure_ascii=False),
            },
            where="paper_id = ?",
            where_params=("paper-search-n1",),
        )
        db.update(
            table="papers",
            data={
                "year": 2021,
                "quick_scan": json.dumps({"verdict": "跳过"}, ensure_ascii=False),
            },
            where="paper_id = ?",
            where_params=("paper-search-n2",),
        )

        response = client.post(
            "/api/v1/librarian/search",
            json={
                "condition_group": {
                    "logic": "or",
                    "predicates": [
                        {"field": "meta.year", "op": "between", "value": [2025, 2030]}
                    ],
                    "groups": [
                        {
                            "logic": "and",
                            "predicates": [
                                {
                                    "field": "quick_scan.verdict",
                                    "op": "contains",
                                    "value": "推荐",
                                },
                                {
                                    "field": "meta.year",
                                    "op": "between",
                                    "value": [2023, 2024],
                                },
                            ],
                            "groups": [],
                        }
                    ],
                },
                "limit": 10,
                "offset": 0,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert payload["paper_ids"] == ["paper-search-n1"]

    def test_search_returns_422_for_invalid_field(
        self, client: TestClient, db: Database
    ) -> None:
        _insert_paper(db, "paper-search-invalid")

        response = client.post(
            "/api/v1/librarian/search",
            json={
                "condition_group": {
                    "logic": "and",
                    "predicates": [
                        {"field": "unknown_field", "op": "contains", "value": "x"}
                    ],
                    "groups": [],
                },
                "limit": 10,
                "offset": 0,
            },
        )

        assert response.status_code == 422
        payload = response.json()
        assert payload["detail"]["code"] == "invalid_field"
