"""全局配置管理."""

import os
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

CONFIG_FILE_ENV = "PPX_CONFIG_FILE"
DEFAULT_CONFIG_FILE = Path(__file__).resolve().parents[2] / "config" / "default.toml"


class LLMConfig(BaseModel):
    """LLM 配置模型.

    支持为不同 Agent 配置不同的 LLM 参数。
    """

    model: str = Field(default="gpt-4o", description="模型名称")
    api_key: str | None = Field(default=None, description="API 密钥")
    base_url: str | None = Field(
        default=None,
        description="API 基础 URL (VLLM: http://localhost:8000/v1)",
    )
    temperature: float = Field(default=0.7, description="采样温度")
    max_tokens: int | None = Field(default=4096, description="最大生成 token 数")
    timeout: float = Field(default=600.0, description="请求超时时间（秒）")
    custom_headers: dict[str, str] | None = Field(
        default=None, description="自定义 HTTP 请求头"
    )
    is_vlm: bool = Field(
        default=False,
        description="是否为视觉模型（启用多模态消息处理）",
    )


class AgentLLMConfigs(BaseModel):
    """各 Agent 的 LLM 配置.

    每个 Agent 可以独立配置 LLM 参数，未配置则使用全局默认。
    """

    # Data Process Agents
    extraction: LLMConfig | None = Field(
        default=None, description="ExtractionAgent 配置"
    )
    fact_check: LLMConfig | None = Field(
        default=None, description="FactCheckAgent 配置"
    )

    # Survey Agents
    planner: LLMConfig | None = Field(default=None, description="PlannerAgent 配置")
    writer: LLMConfig | None = Field(default=None, description="WriterAgent 配置")
    reviewer: LLMConfig | None = Field(default=None, description="ReviewerAgent 配置")


class Settings(BaseSettings):
    """应用配置类."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """自定义配置源优先级.

        优先级从高到低：
        1. 初始化参数
        2. 系统环境变量
        3. `.env`
        4. TOML 配置文件（默认 `config/default.toml`，可由 `PPX_CONFIG_FILE` 指定）
        5. 文件密钥
        """
        raw_toml_path = os.getenv(CONFIG_FILE_ENV)
        toml_path = Path(raw_toml_path) if raw_toml_path else DEFAULT_CONFIG_FILE

        toml_settings = TomlConfigSettingsSource(
            settings_cls=settings_cls,
            toml_file=toml_path,
        )

        return (
            init_settings,
            env_settings,
            dotenv_settings,
            toml_settings,
            file_secret_settings,
        )

    # 应用配置
    APP_NAME: str = "Paper Plane X"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    LOG_APP_ONLY: bool = True
    LOG_TO_FILE: bool = True
    LOG_FILE_PATH: Path = Path("./data/logs/backend.log")
    LOG_FILE_MAX_BYTES: int = 10 * 1024 * 1024
    LOG_FILE_BACKUP_COUNT: int = 5

    # 服务器配置
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # 数据目录
    DATA_DIR: Path = Path("./data")

    # Prompt 目录
    PROMPTS_DIR: Path = Path("./prompts")

    # 数据库配置
    DATABASE_URL: str = "sqlite:///./data/app.db"

    # LLM 全局默认配置
    LLM: LLMConfig = Field(default_factory=LLMConfig)

    # 各 Agent 独立 LLM 配置
    AGENT_LLM: AgentLLMConfigs = Field(default_factory=AgentLLMConfigs)

    # MinerU 配置
    MINERU_BASE_URL: str = Field(
        default="http://localhost:7860", description="MinerU API 地址"
    )
    MINERU_OUTPUT_DIR: Path = Field(
        default=Path("./data/papers"), description="MinerU 服务端输出目录参数"
    )

    # Data Process 配置
    DATA_PROCESS_MAX_RETRIES: int = Field(
        default=3, description="事实核查失败最大重试次数"
    )
    DATA_PROCESS_WORKER_COUNT: int = Field(
        default=2, description="后台数据处理 worker 数量"
    )
    DATA_PROCESS_SHUTDOWN_TIMEOUT: float = Field(
        default=5.0,
        description="后台数据处理 worker 池关闭超时时间（秒）",
    )

    @property
    def database_path(self) -> Path:
        """获取数据库文件路径."""
        return self.DATA_DIR / "app.db"

    def ensure_directories(self) -> None:
        """确保必要的目录存在."""
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.MINERU_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)

    def get_prompt_path(self, group: str, filename: str) -> Path:
        """获取 prompt 文件路径.

        Args:
            group: prompt 分组目录（如 data_processor）
            filename: 文件名（如 System.md）

        Returns:
            Path: prompt 文件绝对路径
        """
        return self.PROMPTS_DIR / group / filename

    def load_prompt(self, group: str, filename: str) -> str:
        """加载 prompt 文件内容.

        Args:
            group: prompt 分组目录（如 data_processor）
            filename: 文件名（如 System.md）

        Returns:
            str: prompt 内容

        Raises:
            FileNotFoundError: 当 prompt 文件不存在时抛出
        """
        prompt_path = self.get_prompt_path(group, filename)
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
        return prompt_path.read_text(encoding="utf-8")

    def get_agent_llm_config(self, agent_name: str) -> LLMConfig:
        """获取指定 Agent 的 LLM 配置.

        优先使用 Agent 特定配置，未设置则返回全局默认配置。

        Args:
            agent_name: Agent 名称 (extraction, fact_check, planner, writer, reviewer)

        Returns:
            LLMConfig: LLM 配置
        """
        agent_configs = {
            "extraction": self.AGENT_LLM.extraction,
            "fact_check": self.AGENT_LLM.fact_check,
            "planner": self.AGENT_LLM.planner,
            "writer": self.AGENT_LLM.writer,
            "reviewer": self.AGENT_LLM.reviewer,
        }

        agent_config = agent_configs.get(agent_name)
        if agent_config is not None:
            # 合并配置：Agent 特定值覆盖全局默认值
            global_config = self.LLM.model_dump()
            agent_overrides = {
                k: v for k, v in agent_config.model_dump().items() if v is not None
            }
            return LLMConfig(**{**global_config, **agent_overrides})

        return self.LLM


# 全局配置实例
settings = Settings()
