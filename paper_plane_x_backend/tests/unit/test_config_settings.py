"""Settings tests."""

import tomllib
from pathlib import Path

from paper_plane_x_backend.config import AgentLLMConfigs, LLMConfig, Settings


def test_get_agent_llm_config_merges_overrides() -> None:
    settings = Settings(
        llm=LLMConfig(
            model="global-model",
            api_key="k-global",
            base_url="http://global",
            temperature=0.7,
            max_tokens=2048,
            timeout=60.0,
            custom_headers={"X-G": "1"},
            thinking_enabled=True,
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}},
            is_vlm=False,
        ),
        agent_llm=AgentLLMConfigs(
            extraction=LLMConfig(
                model="extract-model",
                temperature=0.1,
                thinking_enabled=False,
                reasoning_effort="low",
                is_vlm=True,
            )
        ),
    )

    cfg = settings.get_agent_llm_config("extraction")

    assert cfg.model == "extract-model"
    assert cfg.temperature == 0.1
    assert cfg.api_key == "k-global"
    assert cfg.base_url == "http://global"
    # 仅当 Agent 显式设置字段时才覆盖，全局 llm 配置应保留。
    assert cfg.max_tokens == 2048
    assert cfg.thinking_enabled is False
    assert cfg.reasoning_effort == "low"
    assert cfg.extra_body == {"thinking": {"type": "enabled"}}
    assert cfg.is_vlm is True


def test_get_agent_llm_config_inherits_reasoning_defaults_when_unset() -> None:
    settings = Settings(
        llm=LLMConfig(
            model="global-model",
            thinking_enabled=True,
            reasoning_effort="high",
            extra_body={"metadata": {"tier": "global"}},
        ),
        agent_llm=AgentLLMConfigs(
            analysis=LLMConfig(
                model="analysis-model",
            )
        ),
    )

    cfg = settings.get_agent_llm_config("analysis")

    assert cfg.model == "analysis-model"
    assert cfg.thinking_enabled is True
    assert cfg.reasoning_effort == "high"
    assert cfg.extra_body == {"metadata": {"tier": "global"}}


def test_get_agent_llm_config_can_override_extra_body() -> None:
    settings = Settings(
        llm=LLMConfig(
            model="global-model",
            extra_body={"metadata": {"tier": "global"}},
        ),
        agent_llm=AgentLLMConfigs(
            reviewer=LLMConfig(
                model="reviewer-model",
                extra_body={"thinking": {"type": "enabled"}},
            )
        ),
    )

    cfg = settings.get_agent_llm_config("reviewer")

    assert cfg.model == "reviewer-model"
    assert cfg.extra_body == {"thinking": {"type": "enabled"}}


def test_get_agent_llm_config_returns_global_when_missing() -> None:
    settings = Settings(
        llm=LLMConfig(model="global-model", api_key="k", is_vlm=False),
        agent_llm=AgentLLMConfigs(),
    )

    cfg = settings.get_agent_llm_config("writer")

    assert cfg.model == "global-model"
    assert cfg.api_key == "k"
    assert cfg.is_vlm is False


def test_settings_supports_grouped_keys() -> None:
    settings = Settings(
        log={"level": "ERROR", "app_only": False},
        mineru={"output_dir": "./tmp/papers"},
        data_process={"shutdown_timeout": 12.5},
    )

    assert settings.log.level == "ERROR"
    assert settings.log.app_only is False
    assert str(settings.mineru.output_dir) == "tmp/papers"
    assert settings.data_process.shutdown_timeout == 12.5


def test_default_toml_documents_reasoning_switch() -> None:
    config_path = Path(__file__).resolve().parents[2] / "config" / "default.toml"

    data = tomllib.loads(config_path.read_text(encoding="utf-8"))

    assert data["llm"]["thinking_enabled"] is False
