"""ChromaDB 向量存储服务.

MVP 仅索引论文的 synthesis_data.review_summary，避免在当前阶段引入复杂分块策略。
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, cast

import chromadb

from paper_plane_x_backend.models import Paper

logger = logging.getLogger(__name__)

_EMBEDDING_DIM = 64
_DEFAULT_ENABLED = True
_DEFAULT_PERSIST_PATH = "./data/chroma"
_DEFAULT_COLLECTION_NAME = "paper_plane_x"
_DEFAULT_TOP_K = 5


class ChromaStore:
    """论文向量索引服务（MVP）。"""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        persist_path: str | None = None,
        collection_name: str | None = None,
    ) -> None:
        self.enabled = _DEFAULT_ENABLED if enabled is None else enabled
        self.persist_path = (
            _DEFAULT_PERSIST_PATH if persist_path is None else persist_path
        )
        self.collection_name = (
            _DEFAULT_COLLECTION_NAME if collection_name is None else collection_name
        )
        self._client: Any | None = None
        self._collection: Any | None = None

    def _get_collection(self) -> Any | None:
        if not self.enabled:
            return None

        if self._collection is not None:
            return self._collection

        try:
            self._client = chromadb.PersistentClient(path=self.persist_path)
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name
            )
        except Exception as exc:
            logger.warning("event=chroma.init_failed error=%s", exc)
            return None

        return self._collection

    @staticmethod
    def _build_embedding(text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values: list[float] = []

        while len(values) < _EMBEDDING_DIM:
            for byte in digest:
                values.append((byte / 255.0) * 2.0 - 1.0)
                if len(values) >= _EMBEDDING_DIM:
                    break

        return values

    @staticmethod
    def _build_doc_id(project_id: str, paper_id: str) -> str:
        return f"{project_id}:{paper_id}:summary"

    @staticmethod
    def _extract_summary(paper: Paper) -> str | None:
        if not paper.synthesis_data:
            return None
        summary = paper.synthesis_data.get("review_summary")
        if isinstance(summary, str):
            text = summary.strip()
            return text if text else None
        return None

    def upsert_paper(
        self,
        paper: Paper,
        *,
        project_ids: list[str] | None = None,
    ) -> bool:
        """将论文 summary 写入向量库，返回是否发生写入。"""
        collection = self._get_collection()
        if collection is None:
            return False

        summary = self._extract_summary(paper)
        if summary is None:
            logger.info(
                "event=chroma.upsert_skipped paper_id=%s reason=empty_review_summary",
                paper.paper_id,
            )
            return False

        resolved_project_ids = sorted(set(project_ids or []))
        if not resolved_project_ids:
            logger.info(
                "event=chroma.upsert_skipped paper_id=%s reason=no_linked_project",
                paper.paper_id,
            )
            return False

        for project_id in resolved_project_ids:
            doc_id = self._build_doc_id(project_id=project_id, paper_id=paper.paper_id)
            metadata: dict[str, str | int] = {
                "project_id": project_id,
                "paper_id": paper.paper_id,
                "extraction_status": paper.extraction_status.value,
            }
            if paper.title is not None:
                metadata["title"] = paper.title
            if paper.year is not None:
                metadata["year"] = paper.year

            collection.upsert(
                ids=[doc_id],
                documents=[summary],
                metadatas=[metadata],
                embeddings=[self._build_embedding(summary)],
            )
        return True

    def delete_paper(self, *, project_id: str, paper_id: str) -> bool:
        """删除论文向量索引。"""
        collection = self._get_collection()
        if collection is None:
            return False

        doc_id = self._build_doc_id(project_id=project_id, paper_id=paper_id)
        collection.delete(ids=[doc_id])
        return True

    def query_project_papers(
        self,
        *,
        project_id: str,
        query: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """按项目执行向量检索。"""
        collection = self._get_collection()
        if collection is None:
            return []

        top_k = limit if limit is not None else _DEFAULT_TOP_K
        top_k = max(1, top_k)

        result = cast(
            dict[str, Any],
            collection.query(
                query_embeddings=[self._build_embedding(query)],
                n_results=top_k,
                where={"project_id": project_id},
                include=["documents", "metadatas", "distances"],
            ),
        )

        documents_raw = result.get("documents", [])
        metadatas_raw = result.get("metadatas", [])
        distances_raw = result.get("distances", [])

        documents = (
            cast(list[list[Any]], documents_raw)
            if isinstance(documents_raw, list)
            else []
        )
        metadatas = (
            cast(list[list[Any]], metadatas_raw)
            if isinstance(metadatas_raw, list)
            else []
        )
        distances = (
            cast(list[list[Any]], distances_raw)
            if isinstance(distances_raw, list)
            else []
        )

        rows: list[dict[str, Any]] = []
        docs = documents[0] if documents else []
        metas = metadatas[0] if metadatas else []
        dists = distances[0] if distances else []

        for idx, document in enumerate(docs):
            metadata_raw: Any = metas[idx] if idx < len(metas) else {}
            metadata = (
                cast(dict[str, Any], metadata_raw)
                if isinstance(metadata_raw, dict)
                else {}
            )
            distance = dists[idx] if idx < len(dists) else None
            rows.append(
                {
                    "document": document,
                    "metadata": metadata,
                    "distance": distance,
                }
            )

        return rows


_chroma_store_instance: ChromaStore | None = None


def get_chroma_store() -> ChromaStore:
    global _chroma_store_instance
    if _chroma_store_instance is None:
        _chroma_store_instance = ChromaStore()
    return _chroma_store_instance
