from datetime import datetime, timedelta
from typing import Final

from litellm.proxy.management_endpoints.qos_video_reviews import ReviewVideoRow, review_video
from litellm.types.qos import QosVideoReview

CREATED: Final = datetime(2026, 10, 29, 9, 0)


def _row(reviews: dict[str, QosVideoReview]) -> ReviewVideoRow:
    return ReviewVideoRow(
        video_id="video-1",
        created_at=CREATED,
        model_group="LTX-2",
        prompt="固定镜头：阳光下的绿色草地上，一个红色皮球从画面左侧向右滚动，蓝天上飘着白云",
        reviews=reviews,
        ai_review=None,
        completed_at=CREATED + timedelta(minutes=2),
        status="completed",
    )


def test_a_video_averages_every_reviewers_overall_rating_and_shows_the_callers_own_review() -> None:
    mine: Final = QosVideoReview(overall=5, motion=4, reviewed_at=CREATED)
    theirs: Final = QosVideoReview(overall=2, comment="the face melts", reviewed_at=CREATED)

    video: Final = review_video(_row({"me": mine, "them": theirs}), "me")

    assert (video.reviews, video.overall, video.my_review) == (2, 3.5, mine)


def test_a_video_nobody_rated_has_no_average_and_no_review_of_the_caller() -> None:
    video: Final = review_video(_row({"them": QosVideoReview(overall=3, reviewed_at=CREATED)}), "me")
    unrated: Final = review_video(_row({}), "me")

    assert (video.reviews, video.overall, video.my_review) == (1, 3.0, None)
    assert (unrated.reviews, unrated.overall, unrated.my_review) == (0, None, None)
