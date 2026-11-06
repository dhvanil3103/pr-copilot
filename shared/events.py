from typing import Literal

from pydantic import BaseModel


class PullRequestEventV1(BaseModel):
    """Published by the API, consumed by the worker.

    The version lives in the payload so consumers can handle old and new
    messages side by side during a rolling deploy.
    """

    version: Literal[1] = 1
    review_id: int
    delivery_id: str
    repo_full_name: str
    pr_number: int
    head_sha: str
    installation_id: int

    @property
    def message_key(self) -> str:
        return partition_key(self.repo_full_name, self.pr_number)


def partition_key(repo_full_name: str, pr_number: int) -> str:
    # Same PR -> same partition -> events for one PR are processed in order.
    return f"{repo_full_name}#{pr_number}"
