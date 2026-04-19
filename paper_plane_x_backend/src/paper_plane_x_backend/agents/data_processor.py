"""数据处理器 Agent 实现.

实现论文数据提取和事实核查的 Agent 组：
- 继承式 Agent：ExtractionAgent / FactCheckAgent
- 编排器：DataProcessorAgentGroup（提取-核查闭环）
"""

import asyncio
import json
import logging
from typing import Any, Generic, TypeVar, cast

from pydantic import BaseModel

from paper_plane_x_backend.config import LLMConfig, settings
from paper_plane_x_backend.core.agent_runtime import BaseAgent
from paper_plane_x_backend.schemas.agent_io.data_processor import (
    AnalysisAgentOutput,
    AnalysisAgentUserInput,
    ExtractionAgentOutput,
    ExtractionAgentUserInput,
    FactCheckAgentOutput,
    FactCheckAgentUserInput,
)

logger = logging.getLogger(__name__)

TOutput = TypeVar("TOutput", bound=BaseModel)


class StructuredDataProcessorAgent(Generic[TOutput]):
    """DataProcessor 子域的结构化 Agent 抽象基类。"""

    output_schema: type[TOutput]
    agent_name: str
    llm_config_name: str
    prompt_filename: str

    def __init__(self, llm_config: LLMConfig | None = None) -> None:
        self.llm_config = llm_config or settings.get_agent_llm_config(
            self.llm_config_name
        )

        self._agent = BaseAgent(
            output_schema=self.output_schema,
            mode="api",
            system_prompt=self._build_system_prompt(),
            max_steps=3,
            save_trace=True,
            llm_config=self.llm_config,
            agent_name=self.agent_name,
        )

    def _build_system_prompt(self) -> str:
        system_md = settings.load_prompt("data_processor", "System.md")
        task_md = settings.load_prompt("data_processor", self.prompt_filename)
        task_md = self._inject_schema_template(
            prompt_template=task_md,
            schema_model=self.output_schema,
        )
        return f"{system_md}\n\n{task_md}"

    @staticmethod
    def _inject_schema_template(
        prompt_template: str,
        schema_model: type[BaseModel],
    ) -> str:
        """将 Pydantic 导出的完整 JSON Schema 注入提示词模板。"""
        schema_json = json.dumps(
            schema_model.model_json_schema(),
            ensure_ascii=False,
            indent=2,
        )
        return prompt_template.replace("{{OUTPUT_SCHEMA_JSON}}", schema_json)

    @property
    def runtime_name(self) -> str:
        return self._agent.agent_name

    @property
    def last_trace_id(self) -> str | None:
        return self._agent.last_trace_id

    def reset_memory(self) -> None:
        self._agent.memory.reset_memory()

    def append_user_message(self, payload: dict[str, Any]) -> None:
        self._agent.memory.append_user_message(payload)

    def append_assistant_message(self, payload: dict[str, Any], *, name: str) -> None:
        self._agent.memory.append_assistant_message(
            content=json.dumps(payload, ensure_ascii=False),
            name=name,
        )

    async def run(self) -> TOutput:
        result = await self._agent.run()
        assert isinstance(result, self.output_schema), (
            f"Expected output of type {self.output_schema.__name__}, "
            f"but got {type(result).__name__}"
        )
        return result


class ExtractionAgent(StructuredDataProcessorAgent[ExtractionAgentOutput]):
    """数据提取 Agent。"""

    output_schema = ExtractionAgentOutput
    agent_name = "ExtractionAgent"
    llm_config_name = "extraction"
    prompt_filename = "Extraction.md"

    @staticmethod
    def build_user_message(md_content: str, images: list[str]) -> dict[str, Any]:
        return ExtractionAgentUserInput(
            md_content=md_content,
            images=images,
        ).model_dump()


class AnalysisAgent(StructuredDataProcessorAgent[AnalysisAgentOutput]):
    """理论分析 Agent。"""

    output_schema = AnalysisAgentOutput
    agent_name = "AnalysisAgent"
    llm_config_name = "analysis"
    prompt_filename = "Analysis.md"

    @staticmethod
    def build_user_message(md_content: str, images: list[str]) -> dict[str, Any]:
        return AnalysisAgentUserInput(
            md_content=md_content,
            images=images,
        ).model_dump()


class FactCheckAgent(StructuredDataProcessorAgent[FactCheckAgentOutput]):
    """事实核查 Agent。"""

    output_schema = FactCheckAgentOutput
    agent_name = "FactCheckAgent"
    llm_config_name = "fact_check"
    prompt_filename = "Fact_Check.md"

    @staticmethod
    def build_user_message(md_content: str, images: list[str]) -> dict[str, Any]:
        return FactCheckAgentUserInput(
            md_content=md_content,
            images=images,
        ).model_dump()


class DataProcessorAgentGroup:
    """提取-核查闭环编排器。"""

    def __init__(
        self,
        extraction_agent: ExtractionAgent | None = None,
        fact_check_agent1: FactCheckAgent | None = None,
        analysis_agent: AnalysisAgent | None = None,
        fact_check_agent2: FactCheckAgent | None = None,
    ) -> None:
        self.extraction_agent = extraction_agent or ExtractionAgent()
        self.fact_check_agent1 = fact_check_agent1 or FactCheckAgent()
        self.analysis_agent = analysis_agent or AnalysisAgent()
        self.fact_check_agent2 = fact_check_agent2 or FactCheckAgent()
        self.extraction_last_fact_check_trace_id: str | None = None
        self.analysis_last_fact_check_trace_id: str | None = None

    async def run_extraction_fact_check_loop(
        self,
        *,
        md_content: str,
        images: list[str],
        max_retries: int,
    ) -> tuple[ExtractionAgentOutput, FactCheckAgentOutput, int]:
        extraction_result: ExtractionAgentOutput | None = None
        fact_check_result: FactCheckAgentOutput | None = None
        retry_count = 0
        self.extraction_last_fact_check_trace_id = None

        self.extraction_agent.reset_memory()
        self.fact_check_agent1.reset_memory()

        self.extraction_agent.append_user_message(
            self.extraction_agent.build_user_message(
                md_content=md_content, images=images
            )
        )
        self.fact_check_agent1.append_user_message(
            self.fact_check_agent1.build_user_message(
                md_content=md_content, images=images
            )
        )

        while retry_count < max_retries:
            extraction_result = await self.extraction_agent.run()

            extraction_message = {"extraction_result": extraction_result.model_dump()}
            self.extraction_agent.append_assistant_message(
                extraction_message,
                name=self.extraction_agent.runtime_name,
            )
            self.fact_check_agent1.append_assistant_message(
                extraction_message,
                name=self.extraction_agent.runtime_name,
            )

            fact_check_result_raw: Any = await self.fact_check_agent1.run()
            if fact_check_result_raw is None:
                raise RuntimeError("Fact check result is empty after extraction loop")
            fact_check_result = cast(FactCheckAgentOutput, fact_check_result_raw)

            self.extraction_last_fact_check_trace_id = (
                self.fact_check_agent1.last_trace_id
            )
            fact_check_message = {"fact_check_result": fact_check_result.model_dump()}

            self.extraction_agent.append_assistant_message(
                fact_check_message,
                name=self.fact_check_agent1.runtime_name,
            )
            self.fact_check_agent1.append_assistant_message(
                fact_check_message,
                name=self.fact_check_agent1.runtime_name,
            )

            if fact_check_result.is_passed:
                logger.info(
                    "event=data_processor.fact_check_passed attempts=%s",
                    retry_count + 1,
                )
                break

            logger.warning(
                "event=data_processor.fact_check_failed attempt=%s max_retries=%s error_count=%s",
                retry_count + 1,
                max_retries,
                len(fact_check_result.errors),
            )
            for error in fact_check_result.errors:
                logger.warning(
                    "event=data_processor.fact_check_error_detail field=%s suggestion=%s",
                    error.field_path,
                    error.suggestion,
                )

            retry_count += 1

        if fact_check_result is None:
            raise RuntimeError("Fact check result is empty after fact check loop")

        if not fact_check_result.is_passed:
            logger.warning(
                "event=data_processor.fact_check_waiting_human_review retries=%s",
                retry_count,
            )

        if extraction_result is None:
            raise RuntimeError("Extraction result is empty after fact check passed")

        return extraction_result, fact_check_result, retry_count

    async def run_analysis_fact_check_loop(
        self,
        *,
        md_content: str,
        images: list[str],
        max_retries: int,
    ) -> tuple[AnalysisAgentOutput, FactCheckAgentOutput, int]:
        analysis_result: AnalysisAgentOutput | None = None
        fact_check_result: FactCheckAgentOutput | None = None
        retry_count = 0
        self.analysis_last_fact_check_trace_id = None

        self.analysis_agent.reset_memory()
        self.fact_check_agent2.reset_memory()

        self.analysis_agent.append_user_message(
            self.analysis_agent.build_user_message(md_content=md_content, images=images)
        )
        self.fact_check_agent2.append_user_message(
            self.fact_check_agent2.build_user_message(
                md_content=md_content, images=images
            )
        )

        while retry_count < max_retries:
            analysis_result = await self.analysis_agent.run()

            analysis_message = {"analysis_result": analysis_result.model_dump()}
            self.analysis_agent.append_assistant_message(
                analysis_message,
                name=self.analysis_agent.runtime_name,
            )
            self.fact_check_agent2.append_assistant_message(
                analysis_message,
                name=self.analysis_agent.runtime_name,
            )

            fact_check_result_raw: Any = await self.fact_check_agent2.run()
            if fact_check_result_raw is None:
                raise RuntimeError("Fact check result is empty after analysis loop")
            fact_check_result = cast(FactCheckAgentOutput, fact_check_result_raw)

            self.analysis_last_fact_check_trace_id = (
                self.fact_check_agent2.last_trace_id
            )
            fact_check_message = {"fact_check_result": fact_check_result.model_dump()}

            self.analysis_agent.append_assistant_message(
                fact_check_message,
                name=self.fact_check_agent2.runtime_name,
            )
            self.fact_check_agent2.append_assistant_message(
                fact_check_message,
                name=self.fact_check_agent2.runtime_name,
            )

            if fact_check_result.is_passed:
                logger.info(
                    "event=data_processor.analysis_fact_check_passed attempts=%s",
                    retry_count + 1,
                )
                break

            logger.warning(
                "event=data_processor.analysis_fact_check_failed attempt=%s max_retries=%s error_count=%s",
                retry_count + 1,
                max_retries,
                len(fact_check_result.errors),
            )
            for error in fact_check_result.errors:
                logger.warning(
                    "event=data_processor.analysis_fact_check_error_detail field=%s suggestion=%s",
                    error.field_path,
                    error.suggestion,
                )

            retry_count += 1

        if fact_check_result is None:
            raise RuntimeError(
                "Fact check result is empty after analysis fact check loop"
            )

        if not fact_check_result.is_passed:
            logger.warning(
                "event=data_processor.analysis_fact_check_waiting_human_review retries=%s",
                retry_count,
            )

        if analysis_result is None:
            raise RuntimeError("Analysis result is empty after fact check passed")

        return analysis_result, fact_check_result, retry_count

    async def run_parallel_loops(
        self,
        *,
        md_content: str,
        images: list[str],
        max_retries: int,
    ) -> tuple[
        ExtractionAgentOutput,
        FactCheckAgentOutput,
        int,
        AnalysisAgentOutput,
        FactCheckAgentOutput,
        int,
    ]:
        try:
            extraction_task = self.run_extraction_fact_check_loop(
                md_content=md_content,
                images=images,
                max_retries=max_retries,
            )
            analysis_task = self.run_analysis_fact_check_loop(
                md_content=md_content,
                images=images,
                max_retries=max_retries,
            )
            extraction_result, analysis_result = await asyncio.gather(
                extraction_task,
                analysis_task,
            )
        except asyncio.CancelledError:
            logger.info("event=data_processor.parallel_loops_canceled")
            raise

        return (
            extraction_result[0],
            extraction_result[1],
            extraction_result[2],
            analysis_result[0],
            analysis_result[1],
            analysis_result[2],
        )
