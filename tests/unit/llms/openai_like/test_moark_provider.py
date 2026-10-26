import json
from typing import Final

import httpx
import pytest
import respx

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


@pytest.mark.parametrize("endpoint", ["https://ai.gitee.com/v1", "https://api.moark.com/v1"])
def test_moark_api_base_override_wins_over_registry_default(endpoint: str) -> None:
    _, provider, api_key, api_base = get_llm_provider(
        model="moark/deepseek-v4.1-flash",
        custom_llm_provider=None,
        api_base=endpoint,
        api_key="test-key",
    )

    assert provider == "moark"
    assert api_base == endpoint
    assert api_key == "test-key"


@pytest.mark.parametrize("endpoint", ["https://ai.gitee.com/v1", "https://api.moark.com/v1"])
@respx.mock
def test_moark_chat_uses_the_configured_endpoint(endpoint: str) -> None:
    route: Final = respx.post(f"{endpoint}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chat-1",
                "object": "chat.completion",
                "created": 1,
                "model": "deepseek-v4.1-flash",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )
    )

    response: Final = litellm.completion(
        model="moark/deepseek-v4.1-flash",
        messages=[{"role": "user", "content": "hi"}],
        api_base=endpoint,
        api_key="test-key",
    )

    assert route.call_count == 1
    request: Final = route.calls[0].request
    assert request.headers["authorization"] == "Bearer test-key"
    assert json.loads(request.content)["model"] == "deepseek-v4.1-flash"
    assert response.choices[0].message.content == "OK"


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


@respx.mock
def test_moark_embedding_posts_to_registry_base_url_with_bearer_key() -> None:
    provider_config: Final = JSONProviderRegistry.get("moark")
    assert provider_config is not None
    route: Final = respx.post(f"{provider_config.base_url}/embeddings").mock(
        return_value=httpx.Response(
            200,
            json={
                "object": "list",
                "data": [{"object": "embedding", "index": 0, "embedding": [0.25, -0.5]}],
                "model": "Qwen3-Embedding-4B",
                "usage": {"prompt_tokens": 3, "total_tokens": 3},
            },
        )
    )

    response: Final = litellm.embedding(model="moark/Qwen3-Embedding-4B", input=["你好"], api_key="moark-test-key")

    assert route.call_count == 1
    request: Final = route.calls[0].request
    assert request.headers["authorization"] == "Bearer moark-test-key"
    assert json.loads(request.content)["model"] == "Qwen3-Embedding-4B"
    assert response.data[0]["embedding"] == [0.25, -0.5]


@respx.mock
def test_moark_rerank_posts_to_registry_base_url_and_maps_results() -> None:
    provider_config: Final = JSONProviderRegistry.get("moark")
    assert provider_config is not None
    route: Final = respx.post(f"{provider_config.base_url}/rerank").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "rerank-1",
                "results": [
                    {"index": 1, "relevance_score": 0.9, "document": "pandas.read_csv"},
                    {"index": 0, "relevance_score": 0.1, "document": "json.dump"},
                ],
                "usage": {"total_tokens": 12},
            },
        )
    )

    response: Final = litellm.rerank(
        model="moark/Qwen3-Reranker-4B",
        query="read a CSV in Python",
        documents=["json.dump", "pandas.read_csv"],
        top_n=2,
        api_key="moark-test-key",
    )

    request: Final = route.calls[0].request
    assert request.headers["authorization"] == "Bearer moark-test-key"
    body: Final = json.loads(request.content)
    assert body["model"] == "Qwen3-Reranker-4B"
    assert body["query"] == "read a CSV in Python"
    assert body["top_n"] == 2
    assert [(result["index"], result["relevance_score"]) for result in response.results] == [(1, 0.9), (0, 0.1)]
    assert response.results[0]["document"] == {"text": "pandas.read_csv"}


def test_json_provider_without_embeddings_endpoint_is_still_rejected() -> None:
    provider_config: Final = JSONProviderRegistry.get("scx-ai")
    assert provider_config is not None
    assert "/v1/embeddings" not in provider_config.supported_endpoints

    with pytest.raises(litellm.exceptions.BadRequestError):
        litellm.embedding(model="scx-ai/GLM-5.2", input=["hi"], api_key="test-key")
