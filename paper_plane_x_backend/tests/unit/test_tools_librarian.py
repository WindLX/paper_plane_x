"""Librarian hybrid retrieval tests."""

from paper_plane_x_backend.services.paper.repository import PaperRepositoryError
from paper_plane_x_backend.tools import librarian


def test_fetch_paper_by_path_function_removed() -> None:
    assert not hasattr(librarian, "fetch_paper_by_path")


def test_matrix_compare_by_paths_tool_success(monkeypatch) -> None:
    class _FakeRepo:
        def __init__(self, _db) -> None:
            pass

        @staticmethod
        def fetch_by_path(
            paper_id: str,
            field_path: str,
        ):
            if paper_id == "p-1" and field_path == "meta.title":
                return "T1"
            raise PaperRepositoryError("bad input")

    monkeypatch.setattr(librarian, "get_db", lambda: object())
    monkeypatch.setattr(librarian, "PaperQueryRepository", _FakeRepo)

    assert librarian.matrix_compare.function is not None
    payload = librarian.matrix_compare.function(
        paper_ids=["p-1"],
        field_paths=["meta.title"],
    )
    assert payload["items"]["p-1"]["meta.title"] == "T1"


def test_search_paper_function_removed() -> None:
    assert not hasattr(librarian, "search_paper")


def test_matrix_compare_by_paths_tool_returns_error_payload(monkeypatch) -> None:
    class _FakeRepo:
        def __init__(self, _db) -> None:
            pass

        @staticmethod
        def fetch_by_path(
            paper_id: str,
            field_path: str,
        ):
            _ = paper_id, field_path
            raise PaperRepositoryError("field_paths cannot be empty")

    monkeypatch.setattr(librarian, "get_db", lambda: object())
    monkeypatch.setattr(librarian, "PaperQueryRepository", _FakeRepo)

    assert librarian.matrix_compare.function is not None
    payload = librarian.matrix_compare.function(
        paper_ids=["p-1"],
        field_paths=[],
    )
    assert payload["paper_ids"] == ["p-1"]
    assert payload["field_paths"] == []
    assert payload["error"] == "field_paths cannot be empty"


def test_matrix_compare_by_paths_tool_strips_citations(monkeypatch) -> None:
    class _FakeRepo:
        def __init__(self, _db) -> None:
            pass

        @staticmethod
        def fetch_by_path(
            paper_id: str,
            field_path: str,
        ):
            _ = paper_id, field_path
            return {
                "text": "核心创新",
                "citations": [{"quote": "Q1", "anchor": "#1"}],
            }

    monkeypatch.setattr(librarian, "get_db", lambda: object())
    monkeypatch.setattr(librarian, "PaperQueryRepository", _FakeRepo)

    assert librarian.matrix_compare.function is not None
    payload = librarian.matrix_compare.function(
        paper_ids=["p-1"],
        field_paths=["synthesis_data.methodology.innovation"],
    )
    value = payload["items"]["p-1"]["synthesis_data.methodology.innovation"]
    assert value["text"] == "核心创新"
    assert "citations" not in value


def test_build_field_paths_guide_contains_meta_and_structured_paths() -> None:
    guide = librarian.build_field_paths_guide()

    assert "meta：" in guide
    assert "meta.raw_pdf_path" in guide
    assert "quick_scan.verdict" in guide
    assert "synthesis_data.methodology.innovation.text" in guide
    assert "analysis_report.core_formulation.objective_function.text" in guide


def test_matrix_compare_description_contains_field_paths_guide() -> None:
    desc = librarian.matrix_compare.description
    assert "可用 field_paths" in desc
    assert "custom_meta.<key>" in desc
