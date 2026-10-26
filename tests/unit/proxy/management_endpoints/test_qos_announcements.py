from typing import Final
from unittest.mock import AsyncMock, MagicMock

import pytest

from litellm.proxy.management_endpoints.qos_announcements import (
    ANNOUNCEMENTS_PARAM,
    MAX_ANNOUNCEMENTS,
    AnnouncementBoard,
    read_board,
    save_board,
    with_announcement,
    without_announcement,
)
from litellm.repositories.config_repository import ConfigParam
from litellm.types.qos import QosAnnouncementCreate


def test_a_new_announcement_goes_first_and_the_oldest_drop_off() -> None:
    board = AnnouncementBoard()
    for index in range(MAX_ANNOUNCEMENTS + 2):
        board = with_announcement(board, QosAnnouncementCreate(title=f" notice {index} "), "admin@example.com")

    assert len(board.announcements) == MAX_ANNOUNCEMENTS
    assert board.announcements[0].title == f"notice {MAX_ANNOUNCEMENTS + 1}"
    assert board.revision == MAX_ANNOUNCEMENTS + 2
    assert len({item.id for item in board.announcements}) == MAX_ANNOUNCEMENTS


def test_removing_an_announcement_keeps_the_others() -> None:
    board: Final = with_announcement(
        with_announcement(AnnouncementBoard(), QosAnnouncementCreate(title="first"), "a"),
        QosAnnouncementCreate(title="second"),
        "a",
    )

    remaining: Final = without_announcement(board, board.announcements[0].id)

    assert [item.title for item in remaining.announcements] == ["first"]
    assert remaining.revision == board.revision + 1


@pytest.mark.asyncio
async def test_the_board_is_empty_until_something_is_posted_and_round_trips_through_storage() -> None:
    repository = MagicMock()
    repository.get_param = AsyncMock(return_value=None)
    assert await read_board(repository) == AnnouncementBoard()

    board: Final = with_announcement(
        AnnouncementBoard(), QosAnnouncementCreate(title="maintenance", body="Sat 2am"), "a"
    )
    repository.set_param_if_revision = AsyncMock(return_value=True)
    assert await save_board(repository, AnnouncementBoard(), board)
    name, stored, revision = repository.set_param_if_revision.await_args.args
    assert (name, revision) == (ANNOUNCEMENTS_PARAM, 0)

    repository.get_param = AsyncMock(return_value=ConfigParam(param_name=name, param_value=stored))
    assert await read_board(repository) == board
