import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from litellm.proxy.management_endpoints.qos_images import (
    MODEL_PROFILES,
    ImageItem,
    ImageModelProfile,
    ImagePlan,
    ImagePrompt,
    ImageRun,
    _model_profiles,
    _request_payload,
    summarize_image_runs,
)


def test_builtin_profiles_have_distinct_prices_and_capabilities(monkeypatch):
    monkeypatch.delenv("QOS_SD35_UNIT_COST_CNY", raising=False)
    profiles = _model_profiles()
    qwen = profiles["qwen-image-2.1-viggle-turbo"]
    sd = profiles["stable-diffusion-3.5-large-turbo"]
    assert qwen.supports_seed and qwen.supports_negative_prompt
    assert not sd.supports_seed and not sd.supports_negative_prompt
    assert sd.unit_cost_cny == 0.03
    assert sd.max_prompt_chars == 2000


def test_sync_model_does_not_receive_seed_or_negative_prompt():
    item = ImageItem(id="0001", prompt_id="p1", prompt="A red apple", seed=42)
    payload = _request_payload("stable-diffusion-3.5-large-turbo", "1024x1024", item, MODEL_PROFILES["stable-diffusion-3.5-large-turbo"])
    assert payload == {
        "model": "stable-diffusion-3.5-large-turbo", "prompt": "A red apple",
        "size": "1024x1024", "n": 1, "response_format": "b64_json",
    }


def test_qwen_adapter_retains_seed_and_negative_prompt():
    item = ImageItem(id="0001", prompt_id="p1", prompt="A bowl of ramen", negative_prompt="chopsticks", seed=42)
    payload = _request_payload("qwen-image-2.1-viggle-turbo", "1024x1024", item, MODEL_PROFILES["qwen-image-2.1-viggle-turbo"])
    assert payload["extra_body"] == {"seed": 42, "negative_prompt": "chopsticks"}


def test_additional_profiles_are_configurable_without_code_changes(monkeypatch):
    monkeypatch.setenv("QOS_IMAGE_MODEL_PROFILES_JSON", json.dumps({
        "new-image-model": {"unit_cost_cny": 0.08, "supports_seed": False},
    }))
    assert _model_profiles()["new-image-model"].unit_cost_cny == 0.08


def test_invalid_profile_and_oversized_plan_are_rejected():
    with pytest.raises(ValidationError):
        ImageModelProfile(unit_cost_cny=0)
    with pytest.raises(ValidationError):
        ImagePlan(model="stable-diffusion-3.5-large-turbo", prompts=tuple(
            ImagePrompt(id=f"p{i}", text="A red apple") for i in range(16)
        ), seeds=(1, 2, 3), max_cost_cny=10)


def test_image_home_summary_uses_completed_requests_and_success_latency(tmp_path):
    now = datetime.now(timezone.utc)
    recent = ImageRun(
        id="img-0123456789abcdef", model="stable-diffusion-3.5-large-turbo",
        status="complete", started_at=now - timedelta(hours=1), concurrency=1,
        size="1024x1024", unit_cost_cny=0.03, estimated_cost_cny=0.09,
        supports_seed=False, items=(
            ImageItem(id="0001", prompt_id="p1", prompt="A", seed=1, status="success", e2e_s=4.5),
            ImageItem(id="0002", prompt_id="p2", prompt="B", seed=1, status="failure", e2e_s=8.0),
            ImageItem(id="0003", prompt_id="p3", prompt="C", seed=1),
        ),
    )
    old = recent.model_copy(update={"id": "img-fedcba9876543210", "started_at": now - timedelta(days=2)})
    for run in (recent, old):
        folder = tmp_path / run.id
        folder.mkdir()
        (folder / "run.json").write_text(run.model_dump_json(), encoding="utf-8")
    summary = summarize_image_runs(tmp_path, now - timedelta(hours=24), now)
    assert (summary.runs, summary.requests, summary.successful, summary.failed, summary.pending) == (1, 2, 1, 1, 1)
    assert summary.p95_e2e_s == 4.5
    assert summary.estimated_cost_cny == 0.06
    assert summary.models == ("stable-diffusion-3.5-large-turbo",)
