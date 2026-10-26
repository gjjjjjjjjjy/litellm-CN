from datetime import datetime
from typing import Final

from litellm.proxy.management_endpoints.qos_activity import (
    ACTIVITY_EVENTS,
    ModelAddedRow,
    NodeTransitionRow,
    model_added_event,
    node_event,
    timeline,
)
from litellm.proxy.management_endpoints.qos_health import DeploymentTarget

_TARGET: Final = DeploymentTarget(provider="openai", api_base="https://ai.gitee.com/v1", upstream_model="GLM-5.3")


def _transition(status: str, hour: int, error: str | None = None) -> NodeTransitionRow:
    return NodeTransitionRow(
        model_name="GLM-5.3",
        model_id="node-a",
        status=status,
        error_message=error,
        checked_at=datetime(2026, 10, 26, hour),
    )


def test_a_node_going_down_keeps_only_the_first_line_of_its_error() -> None:
    event: Final = node_event(
        _transition("unhealthy", 9, "InternalServerError: Connection error.\nstack trace: Traceback ..."),
        {"node-a": _TARGET}.get,
    )

    assert (event.kind, event.vendor, event.error) == (
        "node_down",
        "moark",
        "InternalServerError: Connection error.",
    )


def test_a_recovered_node_carries_no_error_and_a_removed_node_no_vendor() -> None:
    event: Final = node_event(_transition("healthy", 10, "stale"), {}.get)

    assert (event.kind, event.vendor, event.error) == ("node_recovered", "", None)


def test_the_timeline_is_newest_first_and_bounded() -> None:
    nodes: Final = [node_event(_transition("healthy", hour), {}.get) for hour in range(1, 24)]
    models: Final = [
        model_added_event(ModelAddedRow(model_name=f"m{day}", created_at=datetime(2026, 10, day), created_by="admin"))
        for day in range(1, 26)
    ] + [
        model_added_event(ModelAddedRow(model_name="newest", created_at=datetime(2026, 10, 27), created_by="admin"))
    ] * 20

    events: Final = timeline(nodes=nodes, runs=[], models=models)

    assert len(events) == ACTIVITY_EVENTS
    assert events[0].model == "newest"
    assert all(earlier.at >= later.at for earlier, later in zip(events, events[1:]))
