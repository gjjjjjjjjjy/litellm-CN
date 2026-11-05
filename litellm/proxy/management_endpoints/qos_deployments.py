"""What the router knows about a deployment: its model name, provider and endpoint."""

import json
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Final

from pydantic import ConfigDict

from litellm.litellm_core_utils.credential_accessor import CredentialAccessor
from litellm.litellm_core_utils.get_llm_provider_logic import get_llm_provider
from litellm.proxy.management_endpoints.qos_health import DeploymentTarget, vendor_of
from litellm.types.llms.base import LiteLLMBaseModel
from litellm.types.qos import QosTargetDeployment

if TYPE_CHECKING:
    from litellm.router import Router


def deployment_model_groups(llm_router: "Router | None") -> str:
    if llm_router is None:
        return "{}"
    return json.dumps(
        {
            model_id: deployment.model_name
            for model_id in llm_router.get_model_ids()
            if (deployment := llm_router.get_deployment(model_id)) is not None
        }
    )


class DeploymentConnection(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    api_key: str | None = None
    api_base: str | None = None


def deployment_connection(litellm_params: Mapping[str, object]) -> DeploymentConnection:
    """The key and endpoint the deployment's requests use: its stored credential fills what it leaves unset."""
    credential_name: Final = litellm_params.get("litellm_credential_name")
    stored: Final = (
        CredentialAccessor.get_credential_values(credential_name) if isinstance(credential_name, str) else {}
    )
    return DeploymentConnection.model_validate({**stored, **litellm_params})


def deployment_target_lookup(llm_router: "Router | None") -> Callable[[str], DeploymentTarget | None]:
    def target_of(model_id: str) -> DeploymentTarget | None:
        deployment: Final = None if llm_router is None else llm_router.get_deployment(model_id)
        if deployment is None:
            return None
        params: Final = deployment.litellm_params
        api_base: Final = deployment_connection(params.model_dump(exclude_none=True)).api_base
        upstream_model, provider, _, default_api_base = get_llm_provider(
            model=params.model, custom_llm_provider=params.custom_llm_provider, api_base=api_base
        )
        if api_base is not None:
            return DeploymentTarget(provider=provider, api_base=api_base, upstream_model=upstream_model)
        return DeploymentTarget(
            provider=provider,
            api_base=provider if default_api_base is None else default_api_base,
            upstream_model=upstream_model,
        )

    return target_of


def target_deployment(model_id: str, target: DeploymentTarget) -> QosTargetDeployment:
    return QosTargetDeployment(
        model_id=model_id,
        provider=target.provider,
        vendor=vendor_of(target.provider, target.api_base),
        api_base=target.api_base,
        upstream_model=target.upstream_model,
    )
