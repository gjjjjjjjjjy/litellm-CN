import pytest
from pydantic import ValidationError

from litellm.proxy.management_endpoints.qos_images import ImageRating


def rating(**overrides):
    data = {
        "prompt_adherence": 4,
        "structure_correctness": 4,
        "text_applicable": False,
        "image_quality": 4,
        "visual_appeal": 4,
        "hard_conditions_passed": True,
        "notes": "Object edges are slightly soft",
    }
    data.update(overrides)
    return ImageRating(**data)


def test_legacy_rating_still_loads_without_quality_score():
    old = ImageRating(prompt_adherence=3, text_correct=False, artifacts=True)
    assert old.quality_score is None
    assert ImageRating.model_validate_json(old.model_dump_json()).quality_score is None


def test_no_text_reweights_applicable_dimensions():
    assert rating(prompt_adherence=5, structure_correctness=1, image_quality=1, visual_appeal=1).quality_score == 41.2
    assert rating(prompt_adherence=3, structure_correctness=3, image_quality=3, visual_appeal=3).quality_score == 50


def test_text_dimension_and_hard_condition_are_separate():
    result = rating(text_applicable=True, text_accuracy=5, text_correct=True, hard_conditions_passed=False)
    assert result.quality_score == 78.8
    assert result.hard_conditions_passed is False


def test_review_note_is_optional():
    result = rating(notes="")
    assert result.notes == ""
    assert ImageRating.model_validate_json(result.model_dump_json()).quality_score == 75


@pytest.mark.parametrize("changes", [
    {"structure_correctness": None},
    {"text_applicable": True},
    {"text_applicable": False, "text_accuracy": 3},
    {"image_quality": 6},
    {"defect_tags": ["unknown"]},
])
def test_incomplete_or_invalid_new_rating_rejected(changes):
    with pytest.raises(ValidationError):
        rating(**changes)
