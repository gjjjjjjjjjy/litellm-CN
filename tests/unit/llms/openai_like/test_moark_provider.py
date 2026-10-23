from typing import Final

import litellm
from litellm import LlmProviders
from litellm.constants import openai_compatible_providers
from litellm.litellm_core_utils.get_llm_provider_logic import get_llm_provider
from litellm.llms.openai_like.json_loader import JSONProviderRegistry


def test_moark_is_a_registered_openai_compatible_provider() -> None:
    assert LlmProviders.MOARK.value == "moark"
    assert "moark" in litellm.provider_list
    assert "moark" in openai_compatible_providers
    assert JSONProviderRegistry.exists("moark")


def test_moark_prefix_resolves_to_json_registry_base_url() -> None:
    provider_config: Final = JSONProviderRegistry.get("moark")
    assert provider_config is not None

    model, provider, _, api_base = get_llm_provider(
        model="moark/deepseek-v4.1-flash",
        custom_llm_provider=None,
        api_base=None,
        api_key=None,
    )

    assert model == "deepseek-v4.1-flash"
    assert provider == "moark"
    assert api_base == provider_config.base_url


def test_moark_api_base_override_wins_over_registry_default() -> None:
    _, provider, api_key, api_base = get_llm_provider(
        model="moark/deepseek-v4.1-flash",
        custom_llm_provider=None,
        api_base="https://ai.gitee.com/v1",
        api_key="test-key",
    )

    assert provider == "moark"
    assert api_base == "https://ai.gitee.com/v1"
    assert api_key == "test-key"


def test_moark_is_detected_from_its_registry_base_url() -> None:
    provider_config: Final = JSONProviderRegistry.get("moark")
    assert provider_config is not None

    _, provider, _, api_base = get_llm_provider(
        model="deepseek-v4.1-flash",
        custom_llm_provider=None,
        api_base=provider_config.base_url,
        api_key=None,
    )

    assert provider == "moark"
    assert api_base == provider_config.base_url
