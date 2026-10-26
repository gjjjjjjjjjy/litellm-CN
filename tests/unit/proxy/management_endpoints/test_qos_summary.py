from datetime import datetime, timedelta, timezone
from typing import Final

import pytest
from fastapi import HTTPException

from litellm.proxy.management_endpoints.qos_summary import QOS_DEFAULT_WINDOW, QOS_MAX_WINDOW, resolve_window

NOW: Final = datetime(2026, 10, 22, 12, 0, 0)


class TestResolveWindow:
    def test_defaults_to_the_window_ending_now(self) -> None:
        assert resolve_window(None, None, NOW) == (NOW - QOS_DEFAULT_WINDOW, NOW)

    def test_timezone_aware_bounds_are_compared_in_utc(self) -> None:
        start, end = resolve_window(
            datetime(2026, 10, 22, 19, 0, tzinfo=timezone(timedelta(hours=8))),
            datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc),
            NOW,
        )
        assert (start, end) == (datetime(2026, 10, 22, 11, 0), datetime(2026, 10, 22, 12, 0))

    def test_rejects_an_empty_or_inverted_window(self) -> None:
        with pytest.raises(HTTPException) as error:
            resolve_window(NOW, NOW, NOW)
        assert error.value.status_code == 400

    def test_rejects_windows_longer_than_the_maximum(self) -> None:
        with pytest.raises(HTTPException) as error:
            resolve_window(NOW - QOS_MAX_WINDOW - timedelta(seconds=1), NOW, NOW)
        assert error.value.status_code == 400
        assert resolve_window(NOW - QOS_MAX_WINDOW, NOW, NOW)[0] == NOW - QOS_MAX_WINDOW
