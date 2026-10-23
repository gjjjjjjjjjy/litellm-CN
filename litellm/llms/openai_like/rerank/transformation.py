"""
`/rerank` support for JSON-configured providers that list `/v1/rerank` in `supported_endpoints`.

These providers accept and return the Jina-style rerank shape, so the request and response mapping is reused;
only the URL and credentials come from the provider's entry in providers.json.
"""

from collections.abc import Mapping
from typing import Final

from litellm.llms.jina_ai.rerank.transformation import JinaAIRerankConfig
from litellm.llms.openai_like.json_loader import SimpleProviderConfig
from litellm.secret_managers.main import get_secret_str


class JSONProviderRerankConfig(JinaAIRerankConfig):
    def __init__(self, provider: SimpleProviderConfig) -> None:
        self.provider: Final = provider

    def get_supported_cohere_rerank_params(self, model: str) -> list[str]:  # mutable-ok: BaseRerankConfig contract
        return ["query", "top_n", "documents", "return_documents"]

    def get_complete_url(
        self,
        api_base: str | None,
        model: str,
        optional_params: Mapping[str, object] | None = None,
    ) -> str:
        base: Final = self.provider.base_url if api_base is None else api_base
        return f"{base.rstrip('/')}/rerank"

    def validate_environment(
        self,
        headers: Mapping[str, str],
        model: str,
        api_key: str | None = None,
        optional_params: Mapping[str, object] | None = None,
        litellm_params: Mapping[str, object] | None = None,
    ) -> dict[str, str]:  # mutable-ok: BaseRerankConfig contract
        key: Final = api_key or get_secret_str(self.provider.api_key_env)
        if not key:
            raise ValueError(
                f"{self.provider.slug} API key not found. Pass `api_key=...` or set the {self.provider.api_key_env} environment variable."
            )
        provider_headers: Final = {
            "accept": "application/json",
            "content-type": "application/json",
            "authorization": f"Bearer {key}",
        }
        caller_headers: Final = {name: value for name, value in headers.items() if name.lower() not in provider_headers}
        return {**caller_headers, **provider_headers}
