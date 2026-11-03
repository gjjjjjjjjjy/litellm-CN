import asyncio
import base64
import binascii
import itertools
import json
import math
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Final, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator
from typing_extensions import Self

from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.proxy.management_endpoints.qos_access import require_admin, require_image_writer, require_reader


router: Final = APIRouter()
RESULTS_ROOT: Final = Path(os.environ.get("QOS_IMAGE_RESULTS_DIR", "/data/qos-image-runs"))
MAX_IMAGES: Final = 32
RUN_ID: Final = re.compile(r"img-[0-9a-f]{16}")
ITEM_ID: Final = re.compile(r"[0-9]{4}")
ACTIVE_TASKS: set[asyncio.Task[None]] = set()
STORE_LOCK: Final = asyncio.Lock()


class ImagePrompt(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    text: str = Field(min_length=1, max_length=4000)
    check: str = Field(default="", max_length=500)
    negative_prompt: str | None = Field(default=None, max_length=1000)


class ImageModelProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_cost_cny: float = Field(gt=0, le=100, allow_inf_nan=False)
    supports_seed: bool = False
    supports_negative_prompt: bool = False
    max_prompt_chars: int = Field(default=2000, ge=1, le=4000)


def _model_profiles() -> dict[str, ImageModelProfile]:
    profiles = {
        "qwen-image-2.1-viggle-turbo": ImageModelProfile(
            unit_cost_cny=float(os.environ.get("QOS_IMAGE_UNIT_COST_CNY", "0.2")),
            supports_seed=True, supports_negative_prompt=True, max_prompt_chars=4000,
        ),
        "stable-diffusion-3.5-large-turbo": ImageModelProfile(
            unit_cost_cny=float(os.environ.get("QOS_SD35_UNIT_COST_CNY", "0.03")),
        ),
    }
    extra = json.loads(os.environ.get("QOS_IMAGE_MODEL_PROFILES_JSON", "{}"))
    if not isinstance(extra, dict):
        raise ValueError("QOS_IMAGE_MODEL_PROFILES_JSON must be a JSON object")
    for name, value in extra.items():
        if not isinstance(name, str) or not name or not isinstance(value, dict):
            raise ValueError("Each image model profile needs a model name and object value")
        profiles[name] = ImageModelProfile.model_validate(value)
    return profiles


MODEL_PROFILES: Final = _model_profiles()


def _active_model_profiles(deployments: list[dict]) -> dict[str, ImageModelProfile]:
    names: set[str] = set()
    explicit: dict[str, ImageModelProfile] = {}
    invalid: set[str] = set()
    for deployment in deployments:
        name = deployment.get("model_name")
        info = deployment.get("model_info") or {}
        if not isinstance(name, str) or not isinstance(info, dict) or info.get("mode") != "image_generation":
            continue
        names.add(name)
        raw = info.get("qos_image_profile")
        if raw is None:
            continue
        try:
            profile = ImageModelProfile.model_validate(raw)
        except (ValueError, TypeError):
            invalid.add(name)
            continue
        if name in explicit and explicit[name] != profile:
            invalid.add(name)
        explicit[name] = profile
    active: dict[str, ImageModelProfile] = {}
    for name in names - invalid:
        profile = explicit.get(name) or MODEL_PROFILES.get(name)
        if profile is not None:
            active[name] = profile
    return active


class ImagePlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str = Field(min_length=1, max_length=128)
    prompts: tuple[ImagePrompt, ...] = Field(min_length=1, max_length=16)
    seeds: tuple[int, ...] = Field(min_length=1, max_length=4)
    concurrency: int = Field(default=1, ge=1, le=4)
    size: Literal["1024x1024"] = "1024x1024"
    max_cost_cny: float = Field(gt=0, le=100)

    @model_validator(mode="after")
    def valid_plan(self) -> Self:
        if len(self.prompts) * len(self.seeds) > MAX_IMAGES:
            raise ValueError(f"A run may generate at most {MAX_IMAGES} images")
        if len({prompt.id for prompt in self.prompts}) != len(self.prompts):
            raise ValueError("Prompt IDs must be unique")
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("Seeds must be unique")
        if any(seed < 0 or seed > 2147483647 for seed in self.seeds):
            raise ValueError("Seeds must be between 0 and 2147483647")
        return self


class ImageRating(BaseModel):
    model_config = ConfigDict(frozen=True)

    prompt_adherence: int = Field(ge=1, le=5)
    text_correct: bool | None = None
    artifacts: bool | None = None
    notes: str = Field(default="", max_length=1000)
    structure_correctness: int | None = Field(default=None, ge=1, le=5)
    text_accuracy: int | None = Field(default=None, ge=1, le=5)
    text_applicable: bool | None = None
    image_quality: int | None = Field(default=None, ge=1, le=5)
    visual_appeal: int | None = Field(default=None, ge=1, le=5)
    hard_conditions_passed: bool | None = None
    defect_tags: tuple[Literal[
        "count", "spatial", "text", "hands", "perspective", "fusion", "artifacts", "style", "other"
    ], ...] = ()

    @model_validator(mode="after")
    def complete_multidimensional_rating(self) -> Self:
        fields = (self.structure_correctness, self.image_quality, self.visual_appeal, self.hard_conditions_passed, self.text_applicable)
        if any(value is not None for value in fields) and any(value is None for value in fields):
            raise ValueError("All required multidimensional rating fields must be provided together")
        if self.structure_correctness is not None:
            if (self.text_accuracy is not None) != self.text_applicable:
                raise ValueError("Text accuracy must be scored exactly when text is applicable")
            if self.text_applicable and self.text_correct is None:
                raise ValueError("Exact text correctness must be checked for text tasks")
        elif self.text_accuracy is not None:
            raise ValueError("Text accuracy requires a complete multidimensional rating")
        if self.defect_tags and self.structure_correctness is None:
            raise ValueError("Defect tags require a complete multidimensional rating")
        return self

    @computed_field
    @property
    def quality_score(self) -> float | None:
        if self.structure_correctness is None or self.image_quality is None or self.visual_appeal is None:
            return None
        weighted = (
            35 * (self.prompt_adherence - 1) + 25 * (self.structure_correctness - 1)
            + 15 * (self.image_quality - 1) + 10 * (self.visual_appeal - 1)
        )
        weight = 85
        if self.text_accuracy is not None:
            weighted += 15 * (self.text_accuracy - 1)
            weight += 15
        return math.floor(250 * weighted / weight + .5) / 10


class ImageItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    prompt_id: str
    prompt: str
    check: str
    negative_prompt: str | None = None
    seed: int
    status: Literal["pending", "success", "failure"] = "pending"
    e2e_s: float | None = None
    response_s: float | None = None
    queue_s: float | None = None
    run_s: float | None = None
    cost_cny: float | None = None
    task_id: str | None = None
    image_file: str | None = None
    error: str | None = None
    rating: ImageRating | None = None


class ImageRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    model: str
    status: Literal["running", "complete", "interrupted"]
    started_at: datetime
    finished_at: datetime | None = None
    concurrency: int
    size: str
    unit_cost_cny: float
    estimated_cost_cny: float
    supports_seed: bool = True
    owner_user_id: str | None = None
    personal_kind: Literal["sync", "qwen_async"] | None = None  # Retain old run.json compatibility.
    items: tuple[ImageItem, ...]


class ImageHomeSummary(BaseModel):
    window_started_at: datetime
    window_ended_at: datetime
    runs: int
    requests: int
    successful: int
    failed: int
    pending: int
    p95_e2e_s: float | None
    estimated_cost_cny: float
    rated: int
    mean_quality_score: float | None
    models: tuple[str, ...]


def _run_dir(run_id: str) -> Path:
    if RUN_ID.fullmatch(run_id) is None:
        raise HTTPException(status_code=400, detail="Invalid image run ID")
    return RESULTS_ROOT / run_id


def _read_run(run_id: str) -> ImageRun:
    path: Final = _run_dir(run_id) / "run.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image run not found")
    return ImageRun.model_validate_json(path.read_bytes())


def _authorize_run(run: ImageRun, user: UserAPIKeyAuth, write: bool = False) -> None:
    require_reader(user)
    if run.owner_user_id is None:
        require_admin(user)
    elif not user.user_id or run.owner_user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Image run not found")
    elif write:
        require_image_writer(user)


def _write_run(run: ImageRun) -> None:
    directory: Final = _run_dir(run.id)
    directory.mkdir(parents=True, exist_ok=True)
    pending: Final = directory / "run.json.tmp"
    pending.write_bytes(run.model_dump_json().encode("utf-8"))
    pending.replace(directory / "run.json")


def _number(headers: httpx.Headers, name: str) -> float | None:
    raw: Final = headers.get(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def summarize_image_runs(
    root: Path, since: datetime, until: datetime, user_id: str | None = None, include_legacy: bool = True,
) -> ImageHomeSummary:
    runs: list[ImageRun] = []
    for path in root.glob("img-*/run.json"):
        run = ImageRun.model_validate_json(path.read_bytes())
        if since <= run.started_at < until and (
            user_id is None or run.owner_user_id == user_id or (include_legacy and run.owner_user_id is None)
        ):
            runs.append(run)
    items = [item for run in runs for item in run.items]
    successful = [item for item in items if item.status == "success"]
    failed = sum(item.status == "failure" for item in items)
    latencies = sorted(item.e2e_s for item in successful if item.e2e_s is not None)
    scores = [item.rating.quality_score for item in successful if item.rating and item.rating.quality_score is not None]
    return ImageHomeSummary(
        window_started_at=since, window_ended_at=until, runs=len(runs),
        requests=len(successful) + failed, successful=len(successful), failed=failed,
        pending=sum(item.status == "pending" for item in items),
        p95_e2e_s=latencies[math.ceil(.95 * len(latencies)) - 1] if latencies else None,
        estimated_cost_cny=round(sum(
            sum(item.status != "pending" for item in run.items) * run.unit_cost_cny for run in runs
        ), 2),
        rated=len(scores), mean_quality_score=round(sum(scores) / len(scores), 1) if scores else None,
        models=tuple(sorted({run.model for run in runs})),
    )


def _image_bytes(response: httpx.Response) -> tuple[bytes, str]:
    body: Final = response.json()
    blob: Final = base64.b64decode(body["data"][0]["b64_json"], validate=True)
    if len(blob) > 20_000_000:
        raise ValueError("Image exceeds 20 MB")
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return blob, "png"
    if blob.startswith(b"\xff\xd8"):
        return blob, "jpg"
    if blob.startswith(b"RIFF") and blob[8:12] == b"WEBP":
        return blob, "webp"
    raise ValueError("Gateway returned non-image content")


def _request_payload(model: str, size: str, item: ImageItem, profile: ImageModelProfile) -> dict[str, object]:
    extra_body = {
        **({"seed": item.seed} if profile.supports_seed else {}),
        **({"negative_prompt": item.negative_prompt} if profile.supports_negative_prompt and item.negative_prompt else {}),
    }
    return {
        "model": model, "prompt": item.prompt, "size": size, "n": 1,
        "response_format": "b64_json",
        **({"extra_body": extra_body} if extra_body else {}),
    }


async def _replace_item(run_id: str, item: ImageItem) -> None:
    async with STORE_LOCK:
        run: Final = _read_run(run_id)
        updated: Final = run.model_copy(update={
            "items": tuple(item if previous.id == item.id else previous for previous in run.items),
        })
        _write_run(updated)


async def _generate_one(
    client: httpx.AsyncClient, base_url: str, master_key: str, run_id: str, model: str, size: str,
    item: ImageItem, semaphore: asyncio.Semaphore, profile: ImageModelProfile,
) -> None:
    async with semaphore:
        started: Final = time.perf_counter()
        try:
            response: Final = await client.post(
                f"{base_url}/v1/images/generations",
                headers={"Authorization": f"Bearer {master_key}"},
                json=_request_payload(model, size, item, profile),
            )
            response_s: Final = round(time.perf_counter() - started, 3)
            response.raise_for_status()
            blob, extension = _image_bytes(response)
            file_name: Final = f"{item.id}.{extension}"
            (_run_dir(run_id) / file_name).write_bytes(blob)
            result: Final = item.model_copy(update={
                "status": "success", "e2e_s": round(time.perf_counter() - started, 3),
                "response_s": response_s,
                "queue_s": _number(response.headers, "llm_provider-x-image-queue-s"),
                "run_s": _number(response.headers, "llm_provider-x-image-run-s"),
                "cost_cny": _number(response.headers, "llm_provider-x-image-cost-cny"),
                "task_id": response.headers.get("llm_provider-x-image-task-id"),
                "image_file": file_name,
            })
        except (httpx.HTTPError, ValueError, KeyError, IndexError, binascii.Error, OSError) as error:
            result = item.model_copy(update={
                "status": "failure", "e2e_s": round(time.perf_counter() - started, 3),
                "error": str(error)[:500],
            })
        await _replace_item(run_id, result)


async def _execute(run: ImageRun, base_url: str, master_key: str, profile: ImageModelProfile) -> None:
    status: Literal["complete", "interrupted"] = "complete"
    try:
        semaphore: Final = asyncio.Semaphore(run.concurrency)
        async with httpx.AsyncClient(timeout=httpx.Timeout(1000.0)) as client:
            await asyncio.gather(*(
                _generate_one(client, base_url, master_key, run.id, run.model, run.size, item, semaphore, profile)
                for item in run.items
            ))
    except Exception:
        status = "interrupted"  # rebind-ok: terminal state reflects an unexpected runner failure
    finally:
        async with STORE_LOCK:
            current: Final = _read_run(run.id)
            _write_run(current.model_copy(update={"status": status, "finished_at": datetime.now(timezone.utc)}))


def _start_task(run: ImageRun, base_url: str, master_key: str, profile: ImageModelProfile) -> None:
    task: Final = asyncio.create_task(_execute(run, base_url, master_key, profile))
    ACTIVE_TASKS.add(task)
    task.add_done_callback(ACTIVE_TASKS.discard)


@router.get("/qos/images/config", dependencies=[Depends(user_api_key_auth)])
async def image_config(
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
) -> dict[str, object]:
    require_reader(user_api_key_dict)
    from litellm.proxy.proxy_server import llm_router

    deployments = llm_router.get_model_list() if llm_router is not None else []
    shared = _active_model_profiles(deployments or []) if user_api_key_dict.user_role == LitellmUserRoles.PROXY_ADMIN else {}
    return {
        "max_images": MAX_IMAGES,
        "models": {name: profile.model_dump() for name, profile in shared.items()},
    }


@router.get("/qos/images/home-summary", dependencies=[Depends(user_api_key_auth)], response_model=ImageHomeSummary)
async def image_home_summary(
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
) -> ImageHomeSummary:
    require_reader(user_api_key_dict)
    now = datetime.now(timezone.utc)
    is_admin = user_api_key_dict.user_role == LitellmUserRoles.PROXY_ADMIN
    return summarize_image_runs(
        RESULTS_ROOT, now - timedelta(hours=24), now,
        user_id=None if is_admin else user_api_key_dict.user_id or "__no_user__",
        include_legacy=is_admin,
    )


@router.post("/qos/images/runs", dependencies=[Depends(user_api_key_auth)], response_model=ImageRun)
async def start_image_run(
    request: Request, plan: ImagePlan, user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
) -> ImageRun:
    from litellm.proxy.proxy_server import llm_router, master_key

    require_admin(user_api_key_dict)
    deployments: Final = llm_router.get_model_list() if llm_router is not None else []
    profile = _active_model_profiles(deployments or []).get(plan.model)
    if profile is None:
        raise HTTPException(status_code=400, detail="No image benchmark profile is configured for this model")
    if any(len(prompt.text) > profile.max_prompt_chars for prompt in plan.prompts):
        raise HTTPException(status_code=400, detail=f"Image prompt exceeds this model's {profile.max_prompt_chars} character limit")
    if not profile.supports_negative_prompt and any(prompt.negative_prompt for prompt in plan.prompts):
        raise HTTPException(status_code=400, detail="This model does not support a separate negative_prompt parameter")
    estimated: Final = len(plan.prompts) * len(plan.seeds) * profile.unit_cost_cny
    if estimated > plan.max_cost_cny:
        raise HTTPException(status_code=400, detail=f"Estimated cost ¥{estimated:.2f} exceeds budget")
    if master_key is None:
        raise HTTPException(status_code=500, detail="Gateway master key is required for image benchmark")
    run_id: Final = "img-" + secrets.token_hex(8)
    items: Final = tuple(
        ImageItem(
            id=f"{index:04d}", prompt_id=prompt.id, prompt=prompt.text, check=prompt.check,
            negative_prompt=prompt.negative_prompt, seed=seed,
        )
        for index, (prompt, seed) in enumerate(itertools.product(plan.prompts, plan.seeds), start=1)
    )
    run: Final = ImageRun(
        id=run_id, model=plan.model, status="running", started_at=datetime.now(timezone.utc),
        concurrency=plan.concurrency, size=plan.size, unit_cost_cny=profile.unit_cost_cny,
        estimated_cost_cny=estimated, supports_seed=profile.supports_seed,
        items=items,
    )
    _write_run(run)
    port: Final = request.scope["server"][1]
    base_url: Final = f"http://127.0.0.1:{port}{request.scope.get('root_path', '')}"
    _start_task(run, base_url, master_key, profile)
    return run


@router.get("/qos/images/runs", dependencies=[Depends(user_api_key_auth)], response_model=tuple[ImageRun, ...])
async def list_image_runs(
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
    range: Literal["15m", "1h", "6h", "24h", "7d"] | None = None,
) -> tuple[ImageRun, ...]:
    require_reader(user_api_key_dict)
    if not RESULTS_ROOT.exists():
        return ()
    window_minutes = {"15m": 15, "1h": 60, "6h": 360, "24h": 1440, "7d": 10080}
    since = datetime.now(timezone.utc) - timedelta(minutes=window_minutes[range]) if range else None
    paths: Final = sorted(RESULTS_ROOT.glob("img-*/run.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    visible: list[ImageRun] = []
    for path in paths:
        run = ImageRun.model_validate_json(path.read_bytes())
        if since is not None and run.started_at < since:
            continue
        if run.owner_user_id == user_api_key_dict.user_id and run.owner_user_id is not None:
            visible.append(run)
        elif run.owner_user_id is None and user_api_key_dict.user_role == LitellmUserRoles.PROXY_ADMIN:
            visible.append(run)
        if len(visible) == 50:
            break
    return tuple(visible)


@router.get("/qos/images/runs/{run_id}", dependencies=[Depends(user_api_key_auth)], response_model=ImageRun)
async def get_image_run(
    run_id: str, user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
) -> ImageRun:
    require_reader(user_api_key_dict)
    run = _read_run(run_id)
    _authorize_run(run, user_api_key_dict)
    return run


@router.get("/qos/images/runs/{run_id}/items/{item_id}/image", dependencies=[Depends(user_api_key_auth)])
async def get_image_file(
    run_id: str, item_id: str, user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
) -> FileResponse:
    require_reader(user_api_key_dict)
    if ITEM_ID.fullmatch(item_id) is None:
        raise HTTPException(status_code=400, detail="Invalid image item ID")
    run: Final = _read_run(run_id)
    _authorize_run(run, user_api_key_dict)
    item: Final = next((item for item in run.items if item.id == item_id), None)
    if item is None or item.image_file is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(_run_dir(run_id) / item.image_file)


@router.put("/qos/images/runs/{run_id}/items/{item_id}/rating", dependencies=[Depends(user_api_key_auth)])
async def rate_image(
    run_id: str, item_id: str, rating: ImageRating,
    user_api_key_dict: Annotated[UserAPIKeyAuth, Depends(user_api_key_auth)],
) -> ImageRun:
    require_image_writer(user_api_key_dict)
    if ITEM_ID.fullmatch(item_id) is None:
        raise HTTPException(status_code=400, detail="Invalid image item ID")
    async with STORE_LOCK:
        run: Final = _read_run(run_id)
        _authorize_run(run, user_api_key_dict, write=True)
        item: Final = next((item for item in run.items if item.id == item_id), None)
        if item is None or item.status != "success":
            raise HTTPException(status_code=404, detail="Completed image not found")
        updated: Final = run.model_copy(update={
            "items": tuple(
                entry.model_copy(update={"rating": rating}) if entry.id == item_id else entry
                for entry in run.items
            ),
        })
        _write_run(updated)
    return updated
