import pytest

from shared.config import Settings


@pytest.fixture(autouse=True)
def _ignore_local_env_file(monkeypatch):
    # Settings reads .env from the working directory; a developer's real provider, model and
    # keys there must not change what the tests exercise.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
