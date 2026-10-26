"""
Announcements that proxy admins post on the home dashboard.

They live in one LiteLLM_Config row, written only when its revision is still the one that was read, so two admins
posting at once cannot drop each other's announcement.
"""

import secrets
from datetime import datetime, timezone
from typing import Final

from pydantic import ConfigDict

from litellm.repositories.config_repository import ConfigRepository
from litellm.types.llms.base import LiteLLMBaseModel
from litellm.types.qos import QosAnnouncement, QosAnnouncementCreate

ANNOUNCEMENTS_PARAM: Final = "qos_announcements"
MAX_ANNOUNCEMENTS: Final = 50


class AnnouncementBoard(LiteLLMBaseModel):
    model_config = ConfigDict(frozen=True)

    revision: int = 0
    announcements: tuple[QosAnnouncement, ...] = ()


async def read_board(repository: ConfigRepository) -> AnnouncementBoard:
    param: Final = await repository.get_param(ANNOUNCEMENTS_PARAM)
    return AnnouncementBoard() if param is None else AnnouncementBoard.model_validate(param.param_value)


def with_announcement(board: AnnouncementBoard, draft: QosAnnouncementCreate, author: str) -> AnnouncementBoard:
    """Newest first, keeping at most MAX_ANNOUNCEMENTS."""
    announcement: Final = QosAnnouncement(
        id=secrets.token_hex(8),
        title=draft.title.strip(),
        body=draft.body.strip(),
        author=author,
        created_at=datetime.now(timezone.utc),
    )
    return AnnouncementBoard(
        revision=board.revision + 1,
        announcements=(announcement, *board.announcements)[:MAX_ANNOUNCEMENTS],
    )


def without_announcement(board: AnnouncementBoard, announcement_id: str) -> AnnouncementBoard:
    return AnnouncementBoard(
        revision=board.revision + 1,
        announcements=tuple(item for item in board.announcements if item.id != announcement_id),
    )


async def save_board(repository: ConfigRepository, previous: AnnouncementBoard, board: AnnouncementBoard) -> bool:
    """Write board unless someone changed the announcements since previous was read."""
    return await repository.set_param_if_revision(ANNOUNCEMENTS_PARAM, board.model_dump(mode="json"), previous.revision)
