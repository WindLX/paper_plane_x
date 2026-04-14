"""Settings tests."""

from paper_plane_x_backend.config import AgentLLMConfigs, LLMConfig, Settings


def test_get_agent_llm_config_merges_overrides() -> None:
    settings = Settings(
        LLM=LLMConfig(
            model="global-model",
            api_key="k-global",
            base_url="http://global",
            temperature=0.7,
            max_tokens=2048,
            timeout=60.0,
            custom_headers={"X-G": "1"},
            is_vlm=False,
        ),
        AGENT_LLM=AgentLLMConfigs(
            extraction=LLMConfig(
                model="extract-model",
                temperature=0.1,
                is_vlm=True,
            )
        ),
    )

    cfg = settings.get_agent_llm_config("extraction")

    assert cfg.model == "extract-model"
    assert cfg.temperature == 0.1
    assert cfg.api_key == "k-global"
    assert cfg.base_url == "http://global"
    # 当前实现中，Agent 配置对象的默认值也会参与覆盖。
    assert cfg.max_tokens == 4096
    assert cfg.is_vlm is True


def test_get_agent_llm_config_returns_global_when_missing() -> None:
    settings = Settings(
        LLM=LLMConfig(model="global-model", api_key="k", is_vlm=False),
        AGENT_LLM=AgentLLMConfigs(),
    )

    cfg = settings.get_agent_llm_config("writer")

    assert cfg.model == "global-model"
    assert cfg.api_key == "k"
    assert cfg.is_vlm is False
