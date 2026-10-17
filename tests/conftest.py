"""Shared test setup."""
from __future__ import annotations

import pytest

# config.py loads .env into the environment. Clear the model endpoint settings for every test so a
# real Token Factory key in a developer's .env is never used, and tests never call the real service.
MODEL_ENV = ["AMD_BASE_URL", "AMD_API_KEY", "AMD_MODEL", "AMD_REASONING_EFFORT",
             "VLLM_BASE_URL", "VLLM_API_KEY", "VLLM_MODEL"]


@pytest.fixture(autouse=True)
def _no_real_model_endpoint(monkeypatch):
    for k in MODEL_ENV:
        monkeypatch.delenv(k, raising=False)
