import pytest

from litellm.proxy.management_endpoints.qos_health import vendor_of


@pytest.mark.parametrize(
    ("provider", "api_base", "vendor"),
    [
        ("moark", "https://api.moark.com/v1", "moark"),
        ("moark", "https://moark.internal:8443/v1", "moark"),
        ("openai", "https://ai.gitee.com/v1", "ai.gitee.com"),
        ("hosted_vllm", "http://10.0.0.8:8000/v1", "10.0.0.8"),
        ("openai_like", "https://api.siliconflow.cn/v1/", "api.siliconflow.cn"),
        ("openai", "", "openai"),
    ],
)
def test_an_openai_compatible_deployment_is_named_after_its_endpoint_host(
    provider: str, api_base: str, vendor: str
) -> None:
    assert vendor_of(provider, api_base) == vendor
