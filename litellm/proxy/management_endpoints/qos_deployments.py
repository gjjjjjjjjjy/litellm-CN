"""What the router knows about a deployment: its model name, provider and endpoint."""

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Final

from litellm.litellm_core_utils.get_llm_provider_logic import get_llm_provider
from litellm.proxy.management_endpoints.qos_health import DeploymentTarget, vendor_of
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


def deployment_target_lookup(llm_router: "Router | None") -> Callable[[str], DeploymentTarget | None]:
    def target_of(model_id: str) -> DeploymentTarget | None:
        deployment: Final = None if llm_router is None else llm_router.get_deployment(model_id)
        if deployment is None:
            return None
        params: Final = deployment.litellm_params
        upstream_model, provider, _, default_api_base = get_llm_provider(
            model=params.model, custom_llm_provider=params.custom_llm_provider, api_base=params.api_base
        )
        if params.api_base is not None:
            return DeploymentTarget(provider=provider, api_base=params.api_base, upstream_model=upstream_model)
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
