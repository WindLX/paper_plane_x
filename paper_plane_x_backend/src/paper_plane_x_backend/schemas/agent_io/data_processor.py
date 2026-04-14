from typing import Literal

from pydantic import BaseModel, Field

from .base import CitedText

# --- Quick Scan ---


class QuickScan(BaseModel):
    tags: list[str] = Field(
        ...,
        max_length=5,
        description="提炼 3-5 个工程领域通用标签（如：优化算法, 控制策略, 架构设计）",
    )
    verdict: Literal["推荐精读", "仅作参考", "仅看实验", "无需阅读"] = Field(...)
    reason: str = Field(..., description="用一句话解释给出上述阅读建议的理由")
    quick_summary: str = Field(
        ...,
        description="用严密的一句话总结：例如本文为了解决 [具体问题]，提出了 [核心方法]，将 [指标] 提升了 [数值]",
    )


# --- Synthesis Data 模块定义 ---


class ResearchGap(BaseModel):
    context: CitedText = Field(..., description="该问题在工程领域的应用背景")
    existing_limit: CitedText = Field(..., description="前人方法的主要局限性")
    motivation: CitedText = Field(..., description="本文想要解决的具体技术瓶颈")


class Methodology(BaseModel):
    approach_name: str = Field(
        ..., description="方法全称及缩写（此项纯字符串，无需引用）"
    )
    core_logic: CitedText = Field(..., description="用工程语言简述技术路线")
    innovation: CitedText = Field(..., description="具体的改进措施或独特的架构设计")
    disadvantage: CitedText = Field(
        ...,
        description="批判性地指出该方案目前存在什么问题、困难或缺陷。若无，在 text 中填 'Not Mentioned'",
    )
    future_direction: CitedText = Field(
        ..., description="作者在文中明确提及的未来发展方向"
    )


class KeyResults(BaseModel):
    dataset_env: CitedText = Field(
        ..., description="实验环境、仿真/实验平台或数据集名称"
    )
    baseline: CitedText = Field(..., description="对比的核心基准方法")
    performance: CitedText = Field(
        ..., description="核心量化结果，务必包含具体的对比数值"
    )


class SynthesisData(BaseModel):
    research_gap: ResearchGap = Field(..., description="背景与痛点")
    methodology: Methodology = Field(..., description="方案概要")
    key_results: KeyResults = Field(..., description="关键结果")
    review_summary: CitedText = Field(
        ...,
        description="综述摘要：约 150 字的学术性总结。描述其解决了什么问题 -> 用了什么方法 -> 达到了什么效果 -> 存在什么问题 -> 未来有何发展方向。（作为全文总结，此项务必提供详实的 citations 列表支撑）",
    )


# --- FactCheck Error 定义 ---


class FactCheckError(BaseModel):
    field_path: str = Field(
        ..., description="错误字段的路径，如 'synthesis_data.methodology.core_logic'"
    )
    generated_claim: str = Field(..., description="报告中错误的具体表述")
    actual_truth: str = Field(..., description="原文中实际的表述")
    suggestion: str = Field(..., description="给 Extraction Agent 的明确修改建议")


# --- Agent Input / Output ---
# 对于 Input 字段里的 images，其比较特殊，要求前端传入 base64 编码的图片数据列表，这个 key 后端会当作图片处理，构建成 content part 传给 LLM


class ExtractionAgentUserInput(BaseModel):
    md_content: str = Field(..., description="原始 Markdown 文本内容")
    images: list[str] = Field(
        default_factory=list,
        description="原始 Markdown 中提取的图片数据列表，元素是 base64 编码的图片数据",
    )


class ExtractionAgentOutput(BaseModel):
    quick_scan: QuickScan
    synthesis_data: SynthesisData


class FactCheckAgentUserInput(BaseModel):
    md_content: str
    images: list[str] = Field(
        default_factory=list,
        description="原始 Markdown 中提取的图片数据列表，元素是 base64 编码的图片数据",
    )


class FactCheckAgentOutput(BaseModel):
    is_passed: bool = Field(..., description="是否通过事实核查")
    errors: list[FactCheckError] = Field(..., description="事实核查中发现的错误列表")
