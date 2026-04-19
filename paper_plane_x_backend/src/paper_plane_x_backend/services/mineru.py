import asyncio
import base64
import logging
import re
from enum import Enum
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlparse

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class Backend(str, Enum):
    PIPELINE = "pipeline"
    VLM_AUTO = "vlm-auto-engine"
    VLM_HTTP = "vlm-http-client"
    HYBRID_AUTO = "hybrid-auto-engine"


class ParseMethod(str, Enum):
    AUTO = "auto"
    TXT = "txt"
    OCR = "ocr"


class MinerUOutput(BaseModel):
    md_content: str
    image_paths: list[Path]


class MinerUClient:
    def __init__(self, base_url: str, output_dir: str | Path = "./output"):
        self.base_url = base_url.rstrip("/")
        self.parse_endpoint = f"{self.base_url}/file_parse"
        self.output_dir = Path(output_dir)

    async def parse_pdf(
        self,
        file_path: str | Path,
        output_md_name: str,
        save_dir: str | Path,
        output_dir: str | Path | None = None,
        lang_list: list[str] = ["ch"],
        backend: Backend = Backend.HYBRID_AUTO,
        parse_method: ParseMethod = ParseMethod.AUTO,
        formula_enable: bool = True,
        table_enable: bool = True,
        server_url: str | None = None,
        return_md: bool = True,
        return_middle_json: bool = False,
        return_model_output: bool = False,
        return_content_list: bool = False,
        return_images: bool = True,
        response_format_zip: bool = False,
        start_page_id: int = 0,
        end_page_id: int = 99999,
    ) -> MinerUOutput:
        file_path = Path(file_path)
        if not file_path.exists():
            logger.warning("event=mineru.parse_file_not_found file_path=%s", file_path)
            raise FileNotFoundError(f"File not found: {file_path}")

        effective_output_dir = (
            Path(output_dir) if output_dir is not None else self.output_dir
        )

        payload: dict[str, Any] = {
            "output_dir": str(effective_output_dir),
            "backend": backend.value,
            "parse_method": parse_method.value,
            "formula_enable": str(formula_enable).lower(),
            "table_enable": str(table_enable).lower(),
            "return_md": str(return_md).lower(),
            "return_middle_json": str(return_middle_json).lower(),
            "return_model_output": str(return_model_output).lower(),
            "return_content_list": str(return_content_list).lower(),
            "return_images": str(return_images).lower(),
            "response_format_zip": str(response_format_zip).lower(),
            "start_page_id": str(start_page_id),
            "end_page_id": str(end_page_id),
        }

        if server_url:
            payload["server_url"] = server_url

        file_bytes = await asyncio.to_thread(file_path.read_bytes)
        files = {"files": (file_path.name, file_bytes, "application/pdf")}
        payload["lang_list"] = lang_list
        logger.info(
            "event=mineru.parse_started endpoint=%s file=%s backend=%s parse_method=%s lang_list=%s",
            self.parse_endpoint,
            file_path,
            backend.value,
            parse_method.value,
            lang_list,
        )

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(
                    self.parse_endpoint,
                    data=payload,
                    files=files,
                )

                if response.status_code != 200:
                    logger.error(
                        "event=mineru.parse_http_error status=%s file=%s",
                        response.status_code,
                        file_path,
                    )
                    raise RuntimeError(
                        f"HTTP Error {response.status_code}: {response.text}"
                    )

                logger.info(
                    "event=mineru.parse_response_received status=%s file=%s",
                    response.status_code,
                    file_path,
                )
                return self._parse_response(response, output_md_name, save_dir)

        except httpx.HTTPStatusError as e:
            logger.exception(
                "event=mineru.parse_http_status_exception file=%s", file_path
            )
            raise RuntimeError(
                f"HTTP Error {e.response.status_code}: {e.response.text}"
            )
        except Exception as e:
            logger.exception("event=mineru.parse_failed file=%s", file_path)
            raise RuntimeError(f"Connection failed: {str(e)}")

    def _parse_response(
        self, response: httpx.Response, output_md_name: str, save_dir: str | Path
    ) -> MinerUOutput:
        data = cast(dict[str, Any], response.json())

        results = data.get("results")

        if not results or not isinstance(results, dict):
            logger.error("event=mineru.response_invalid_results")
            raise ValueError(
                "Invalid response format: 'results' field missing or invalid"
            )

        results_dict = cast(dict[str, Any], results)

        try:
            first_file_result = next(iter(results_dict.values()))
        except StopIteration:
            logger.error("event=mineru.response_empty_results")
            raise ValueError("Invalid response format: 'results' is empty")

        if not isinstance(first_file_result, dict):
            logger.error("event=mineru.response_invalid_first_result")
            raise ValueError("Invalid result format: expected a dictionary")

        first_result_dict = cast(dict[str, Any], first_file_result)

        md_content = first_result_dict.get("md_content")

        if not md_content or not isinstance(md_content, str):
            logger.error("event=mineru.response_missing_md_content")
            raise ValueError(
                "'md_content' not found or invalid in result. Keys: "
                f"{list(first_result_dict.keys())}"
            )

        save_dir = Path(save_dir)
        image_save_dir = save_dir / "images"
        image_save_dir.mkdir(parents=True, exist_ok=True)

        with open(save_dir / output_md_name, "w", encoding="utf-8") as md_file:
            md_file.write(md_content)
        logger.info("event=mineru.markdown_saved path=%s", save_dir / output_md_name)

        images_info_raw = first_result_dict.get("images", {})
        images_info: dict[str, str] = {}
        if isinstance(images_info_raw, dict):
            for key, value in cast(dict[Any, Any], images_info_raw).items():
                if isinstance(key, str) and isinstance(value, str):
                    images_info[key] = value
        decoded_image_count = 0
        for img_name, img_data in images_info.items():
            if not img_data.startswith("data:image"):
                continue
            base64_data = img_data.split(",", 1)[1]
            img_bytes = base64.b64decode(base64_data)

            img_path = image_save_dir / img_name
            with open(img_path, "wb") as img_file:
                img_file.write(img_bytes)
            decoded_image_count += 1

        logger.info(
            "event=mineru.images_decoded count=%s image_dir=%s",
            decoded_image_count,
            image_save_dir,
        )

        self._prune_unreferenced_images(md_content, image_save_dir)

        image_paths = self._get_image_paths(md_content, image_save_dir)
        logger.info(
            "event=mineru.parse_artifacts_ready referenced_image_count=%s save_dir=%s",
            len(image_paths),
            save_dir,
        )

        return MinerUOutput(md_content=md_content, image_paths=image_paths)

    def load_md(self, md_name: str, save_dir: str | Path) -> MinerUOutput:
        save_dir = Path(save_dir)
        md_path = save_dir / md_name

        if not md_path.exists():
            logger.warning("event=mineru.markdown_load_file_not_found path=%s", md_path)
            raise FileNotFoundError(f"Markdown file not found: {md_path}")

        md_content = md_path.read_text(encoding="utf-8")
        image_paths = self._get_image_paths(md_content, save_dir / "images")
        logger.debug(
            "event=mineru.markdown_loaded path=%s referenced_image_count=%s",
            md_path,
            len(image_paths),
        )

        return MinerUOutput(md_content=md_content, image_paths=image_paths)

    def _get_image_paths(self, md_content: str, image_dir: Path) -> list[Path]:
        if not image_dir.exists():
            return []

        referenced_names = self._extract_referenced_image_names(md_content)
        image_paths: list[Path] = []
        for file_name in sorted(referenced_names):
            candidate = image_dir / file_name
            if candidate.exists() and candidate.is_file():
                image_paths.append(candidate)
        return image_paths

    def _prune_unreferenced_images(self, md_content: str, image_dir: Path) -> None:
        if not image_dir.exists():
            return

        referenced_names = self._extract_referenced_image_names(md_content)
        removed_count = 0
        for candidate in image_dir.iterdir():
            if not candidate.is_file():
                continue
            if candidate.name not in referenced_names:
                candidate.unlink(missing_ok=True)
                removed_count += 1

        if removed_count:
            logger.info(
                "event=mineru.images_pruned removed_count=%s image_dir=%s",
                removed_count,
                image_dir,
            )

    def _extract_referenced_image_names(self, md_content: str) -> set[str]:
        references: set[str] = set()

        md_pattern = r"!\[[^\]]*\]\(([^)]+)\)"
        html_pattern = r"<img[^>]+src=[\"']([^\"']+)[\"'][^>]*>"

        for raw_ref in cast(list[str], re.findall(md_pattern, md_content)):
            ref = raw_ref.strip()
            # markdown image 可能带标题: ![](path \"title\")
            if " " in ref:
                ref = ref.split(" ", 1)[0]
            ref = ref.strip("<>'\"")
            parsed_path = Path(unquote(urlparse(ref).path))
            if parsed_path.name:
                references.add(parsed_path.name)

        for raw_ref in cast(
            list[str], re.findall(html_pattern, md_content, flags=re.IGNORECASE)
        ):
            ref = raw_ref.strip("<>'\"")
            parsed_path = Path(unquote(urlparse(ref).path))
            if parsed_path.name:
                references.add(parsed_path.name)

        return references
