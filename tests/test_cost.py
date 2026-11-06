import pytest

from shared.config import DEFAULT_MODEL_PRICES, ModelPrice, Settings
from shared.cost import estimate_cost_usd


def test_cost_uses_per_million_prices():
    prices = {"m": ModelPrice(input=1.0, output=5.0)}
    assert estimate_cost_usd("m", 1_000_000, 200_000, prices) == pytest.approx(2.0)


def test_unknown_model_costs_zero():
    assert estimate_cost_usd("unknown", 10, 10, DEFAULT_MODEL_PRICES) == 0.0


def test_prices_can_be_overridden_from_env(monkeypatch):
    monkeypatch.setenv("MODEL_PRICES", '{"claude-haiku-4-5": {"input": 9, "output": 9}}')
    assert Settings().model_prices["claude-haiku-4-5"].input == 9


def test_per_agent_model_override():
    s = Settings(default_model="cheap", test_agent_model="smart")
    assert s.model_for("review") == "cheap"
    assert s.model_for("test") == "smart"
