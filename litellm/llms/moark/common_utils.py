from collections.abc import Mapping
from typing import Final

from litellm.llms.base_llm.chat.transformation import BaseLLMException
from litellm.llms.openai_like.json_loader import JSONProviderRegistry, SimpleProviderConfig
from litellm.secret_managers.main import get_secret_str

MOARK: Final = "moark"


class MoarkError(BaseLLMException):
    pass


def _registered() -> SimpleProviderConfig:
    config: Final = JSONProviderRegistry.get(MOARK)
    if config is None:
        raise ValueError("litellm/llms/openai_like/providers.json has no moark entry")
    return config


def moark_api_base(api_base: str | None) -> str:
    config: Final = _registered()
    registered_base: Final = config.base_url if isinstance(config.base_url, str) else ""
    configured: Final = api_base or (get_secret_str(config.api_base_env) if config.api_base_env else None)
    return (configured or registered_base).rstrip("/")


def moark_auth_headers(api_key: str | None) -> Mapping[str, str]:
    key_env: Final = _registered().api_key_env
    key: Final = api_key or get_secret_str(key_env)
    if key is None:
        raise ValueError(f"Moark API key is required: set {key_env} or pass api_key")
    return {"Authorization": f"Bearer {key}"}
