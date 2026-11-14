"""The single LLM client wrapper.

Every LLM call in the project must go through this module so that the provider
and the models stay swappable through `.env` alone.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
import re
import time
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    BadRequestError,
    UnprocessableEntityError,
)

from app.core.config import get_settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.0

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)

_client: AsyncOpenAI | None = None
_semaphore: asyncio.Semaphore | None = None
# Models whose provider rejected `response_format=json_object`.
_json_mode_unsupported: set[str] = set()


class InvalidJSONError(ValueError):
    """The model answered, but no JSON object could be extracted."""


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncOpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout=settings.llm_timeout,
            max_retries=0,  # retries are handled here, in one place
        )
    return _client


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(get_settings().max_concurrency)
    return _semaphore


def _log(level: int, event: str, **fields: Any) -> None:
    logger.log(level, json.dumps({"event": event, **fields}, ensure_ascii=False))


def _outermost_object(text: str) -> str | None:
    """Return the first balanced `{...}` block, ignoring braces inside strings."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    end = text.rfind("}")
    return text[start : end + 1] if end > start else None


def extract_json(text: str | None) -> dict[str, Any]:
    """Parse a JSON object out of a model reply.

    Tries, in order: the raw text, the content of a ``` / ```json fence, and the
    outermost brace-delimited block.
    """
    if not text or not text.strip():
        raise InvalidJSONError("empty model response")

    stripped = text.strip()
    candidates = [stripped]
    candidates.extend(match.strip() for match in _FENCE_RE.findall(stripped))
    block = _outermost_object(stripped)
    if block is not None:
        candidates.append(block)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise InvalidJSONError(f"no JSON object found in response: {stripped[:200]!r}")


def _usage_dict(usage: Any) -> dict[str, int | None]:
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }


def _is_retryable(error: Exception) -> bool:
    if isinstance(error, (APITimeoutError, APIConnectionError, InvalidJSONError)):
        return True
    if isinstance(error, APIStatusError):
        return error.status_code == 429 or error.status_code >= 500
    return False


async def _complete(
    model: str, messages: list[dict[str, Any]]
) -> tuple[str | None, dict[str, int | None]]:
    """One completion call, falling back to plain text if JSON mode is rejected."""
    client = _get_client()
    if model not in _json_mode_unsupported:
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                temperature=0,
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content, _usage_dict(response.usage)
        except (BadRequestError, UnprocessableEntityError) as error:
            _json_mode_unsupported.add(model)
            _log(
                logging.WARNING,
                "llm.json_mode_rejected",
                model=model,
                status=error.status_code,
                error=str(error)[:300],
            )

    response = await client.chat.completions.create(
        model=model,
        messages=messages,  # type: ignore[arg-type]
        temperature=0,
    )
    return response.choices[0].message.content, _usage_dict(response.usage)


async def vision_json(
    model: str,
    system_prompt: str,
    user_text: str,
    image_png_bytes: bytes,
) -> tuple[dict[str, Any], dict[str, int | None]]:
    """Send one PNG plus text to a vision model and return `(parsed_dict, usage)`.

    Retries up to `MAX_RETRIES` times with exponential backoff on 429, 5xx,
    timeouts, connection errors and replies that contain no valid JSON object.
    """
    image_b64 = base64.b64encode(image_png_bytes).decode("ascii")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                },
            ],
        },
    ]

    for attempt in range(MAX_RETRIES + 1):
        started = time.perf_counter()
        try:
            async with _get_semaphore():
                content, usage = await _complete(model, messages)
            parsed = extract_json(content)
        except Exception as error:  # noqa: BLE001 - classified just below
            if not _is_retryable(error) or attempt == MAX_RETRIES:
                _log(
                    logging.ERROR,
                    "llm.vision_json.failed",
                    model=model,
                    attempt=attempt + 1,
                    error_type=type(error).__name__,
                    error=str(error)[:300],
                )
                raise
            delay = BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0, 0.5)
            _log(
                logging.WARNING,
                "llm.vision_json.retry",
                model=model,
                attempt=attempt + 1,
                delay_s=round(delay, 2),
                error_type=type(error).__name__,
                error=str(error)[:300],
            )
            await asyncio.sleep(delay)
            continue

        _log(
            logging.INFO,
            "llm.vision_json.ok",
            model=model,
            attempt=attempt + 1,
            latency_s=round(time.perf_counter() - started, 2),
            json_mode=model not in _json_mode_unsupported,
            **usage,
        )
        return parsed, usage

    raise RuntimeError("unreachable")  # pragma: no cover
