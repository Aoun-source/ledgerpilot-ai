"""Shared test setup."""
from __future__ import annotations

import pytest

# Import config now, at collection: it loads .env into the environment on first import. If that first import
# happened inside a test (after the fixture below cleared the keys), a developer's real keys would come back
# and the test would call the real services.
import ledgerpilot.config  # noqa: E402,F401

# config.py loads .env into the environment. Clear the model endpoint settings for every test so a
# real Token Factory key in a developer's .env is never used, and tests never call the real service.
MODEL_ENV = ["AMD_BASE_URL", "AMD_API_KEY", "AMD_MODEL", "AMD_REASONING_EFFORT",
             "VLLM_BASE_URL", "VLLM_API_KEY", "VLLM_MODEL"]


@pytest.fixture(autouse=True)
def _no_real_model_endpoint(monkeypatch):
    for k in MODEL_ENV:
        monkeypatch.delenv(k, raising=False)
