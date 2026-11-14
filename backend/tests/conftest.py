"""Provide harmless defaults so unit tests never require a developer .env file."""

from __future__ import annotations

import os


# Settings are loaded while importing the application. These values are only
# placeholders: unit tests do not make network or database calls.
_TEST_SETTINGS = {
    "DEMO_MODE": "false",
    "LLM_BASE_URL": "https://example.invalid/v1",
    "LLM_API_KEY": "unit-test-key",
    "VISION_MODEL_A": "unit-test-model-a",
    "VISION_MODEL_B": "unit-test-model-b",
    "VISION_MODEL_PRIMARY": "unit-test-model-a",
    "DATABASE_URL": "postgresql+asyncpg://test:test@127.0.0.1:5432/test",
}

for key, value in _TEST_SETTINGS.items():
    os.environ.setdefault(key, value)
