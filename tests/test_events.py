import pytest
from pydantic import ValidationError

from shared.events import PullRequestEventV1, partition_key


def make_event(**overrides) -> PullRequestEventV1:
    data = dict(
        review_id=1,
        delivery_id="d1",
        repo_full_name="acme/demo",
        pr_number=7,
        head_sha="abc",
        installation_id=9,
    )
    return PullRequestEventV1(**{**data, **overrides})


def test_message_key_groups_events_by_pr():
    assert make_event().message_key == "acme/demo#7"
    assert partition_key("acme/demo", 7) == make_event().message_key


def test_round_trips_through_json():
    event = make_event()
    assert PullRequestEventV1.model_validate_json(event.model_dump_json()) == event


def test_unknown_version_is_rejected():
    payload = make_event().model_dump()
    payload["version"] = 2
    with pytest.raises(ValidationError):
        PullRequestEventV1.model_validate(payload)
