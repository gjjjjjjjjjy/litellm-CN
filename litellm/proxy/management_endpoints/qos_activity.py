"""
What happened on the gateway recently, for the home dashboard: nodes that went down or recovered, benchmark runs and
models that were added. Every event is derived from data the gateway already keeps.
"""

from collections.abc import Callable, Sequence
from datetime import datetime
from itertools import chain
from typing import Final

from pydantic import ConfigDict, TypeAdapter

from litellm.proxy.management_endpoints.qos_health import DeploymentTarget, vendor_of
from litellm.types.llms.base import LiteLLMBaseModel
from litellm.types.qos import QosActivityEvent, QosBenchmarkEvent, QosBenchmarkRun, QosModelAddedEvent, QosNodeEvent

ACTIVITY_EVENTS: Final = 60
ERROR_CHARS: Final = 200

NODE_TRANSITIONS_SQL: Final = """
WITH checks AS (
    SELECT
        model_name,
        COALESCE(model_id, '') AS model_id,
        status,
        error_message,
        checked_at,
        LAG(status) OVER (PARTITION BY COALESCE(model_id, ''), model_name ORDER BY checked_at) AS previous_status
    FROM "LiteLLM_HealthCheckTable"
    WHERE checked_at >= $1::timestamp - interval '1 day'
)
SELECT model_name, model_id, status, error_message, checked_at
FROM checks
WHERE checked_at >= $1::timestamp
    AND status IS DISTINCT FROM previous_status
    AND NOT (previous_status IS NULL AND status = 'healthy')
ORDER BY checked_at DESC
LIMIT 60
"""

MODELS_ADDED_SQL: Final = """
SELECT model_name, created_at, COALESCE(created_by, '') AS created_by
FROM "LiteLLM_ProxyModelTable"
WHERE created_at >= $1::timestamp
ORDER BY created_at DESC
LIMIT 60
"""


class NodeTransitionRow(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model_name: str
    model_id: str
    status: str
    error_message: str | None
    checked_at: datetime


class ModelAddedRow(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    model_name: str
    created_at: datetime
    created_by: str


NODE_TRANSITION_ROWS: Final = TypeAdapter(list[NodeTransitionRow])
MODEL_ADDED_ROWS: Final = TypeAdapter(list[ModelAddedRow])


def node_event(row: NodeTransitionRow, target_of: Callable[[str], DeploymentTarget | None]) -> QosNodeEvent:
    target: Final = target_of(row.model_id)
    down: Final = row.status == "unhealthy"
    return QosNodeEvent(
        kind="node_down" if down else "node_recovered",
        at=row.checked_at,
        model=row.model_name,
        model_id=row.model_id,
        vendor="" if target is None else vendor_of(target.provider, target.api_base),
        error=_headline(row.error_message) if down else None,
    )


def _headline(error_message: str | None) -> str | None:
    """The first line of a health check error, which carries the cause without the stack trace."""
    lines: Final = [] if error_message is None else error_message.strip().splitlines()
    return lines[0][:ERROR_CHARS] if lines else None


def benchmark_event(run: QosBenchmarkRun) -> QosBenchmarkEvent:
    return QosBenchmarkEvent(
        kind="benchmark",
        at=run.last_response_at,
        model=run.model_group,
        run_id=run.run_id,
        requests=run.requests,
        failed_requests=run.failed_requests,
        crosstalk_responses=run.crosstalk_responses,
    )


def model_added_event(row: ModelAddedRow) -> QosModelAddedEvent:
    return QosModelAddedEvent(kind="model_added", at=row.created_at, model=row.model_name, created_by=row.created_by)


def timeline(
    nodes: Sequence[QosNodeEvent], runs: Sequence[QosBenchmarkEvent], models: Sequence[QosModelAddedEvent]
) -> tuple[QosActivityEvent, ...]:
    """All events, newest first, at most ACTIVITY_EVENTS of them."""
    events: Final[list[QosActivityEvent]] = sorted(chain(nodes, runs, models), key=lambda event: event.at, reverse=True)
    return tuple(events[:ACTIVITY_EVENTS])
