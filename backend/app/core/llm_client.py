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
_embedding_client: AsyncOpenAI | None = None
_audio_client: AsyncOpenAI | None = None
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


async def complete_json(model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    """Request structured JSON through the shared LLM wrapper with retries."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            json_messages = list(messages)
            guard = {"role": "system", "content": "Return only one valid JSON object."}
            json_messages.insert(1 if json_messages and json_messages[0]["role"] == "system" else 0, guard)
            async with _get_semaphore():
                content, _usage = await _complete(model, json_messages)
            return extract_json(content)
        except Exception as error:  # noqa: BLE001 - classified below
            if not _is_retryable(error) or attempt == MAX_RETRIES:
                _log(
                    logging.ERROR,
                    "llm.complete_json.failed",
                    model=model,
                    error_type=type(error).__name__,
                    error=str(error)[:300],
                )
                raise
            delay = BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0, 0.5)
            _log(
                logging.WARNING,
                "llm.complete_json.retry",
                model=model,
                attempt=attempt + 1,
                delay_s=round(delay, 2),
                error_type=type(error).__name__,
            )
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable")  # pragma: no cover


def _get_embedding_client() -> AsyncOpenAI:
    global _embedding_client
    if _embedding_client is None:
        settings = get_settings()
        _embedding_client = AsyncOpenAI(
            base_url=settings.embedding_base_url or settings.llm_base_url,
            api_key=settings.embedding_api_key or settings.llm_api_key,
            timeout=settings.llm_timeout,
            max_retries=0,
        )
    return _embedding_client


async def embed_texts(texts: list[str], model: str | None = None) -> list[list[float]]:
    """Create vectors through the configured OpenAI-compatible embedding API."""
    if not texts:
        return []
    settings = get_settings()
    embedding_model = model or settings.embedding_model
    client = _get_embedding_client()

    for attempt in range(MAX_RETRIES + 1):
        try:
            async with _get_semaphore():
                response = await client.embeddings.create(model=embedding_model, input=texts)
            vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
            if len(vectors) != len(texts):
                raise ValueError("embedding response count does not match input count")
            for vector in vectors:
                if len(vector) != settings.embedding_dimension:
                    raise ValueError(
                        f"embedding dimension mismatch: expected {settings.embedding_dimension}, "
                        f"received {len(vector)}"
                    )
            return vectors
        except Exception as error:  # noqa: BLE001 - classified below
            if not _is_retryable(error) or attempt == MAX_RETRIES:
                _log(
                    logging.ERROR,
                    "llm.embed_texts.failed",
                    model=embedding_model,
                    error_type=type(error).__name__,
                    error=str(error)[:300],
                )
                raise
            delay = BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0, 0.5)
            _log(
                logging.WARNING,
                "llm.embed_texts.retry",
                model=embedding_model,
                attempt=attempt + 1,
                delay_s=round(delay, 2),
                error_type=type(error).__name__,
            )
            await asyncio.sleep(delay)

    raise RuntimeError("unreachable")  # pragma: no cover


async def complete_text(model: str, messages: list[dict[str, str]]) -> str:
    """Create a plain-text chat completion through the shared provider client."""
    client = _get_client()
    for attempt in range(MAX_RETRIES + 1):
        started = time.perf_counter()
        try:
            async with _get_semaphore():
                response = await client.chat.completions.create(
                    model=model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=0.2,
                )
            content = response.choices[0].message.content
            if not content or not content.strip():
                raise InvalidJSONError("empty model response")
            _log(
                logging.INFO,
                "llm.complete_text.ok",
                model=model,
                latency_s=round(time.perf_counter() - started, 2),
                **_usage_dict(response.usage),
            )
            return content.strip()
        except Exception as error:  # noqa: BLE001 - classified below
            if not _is_retryable(error) or attempt == MAX_RETRIES:
                _log(
                    logging.ERROR,
                    "llm.complete_text.failed",
                    model=model,
                    error_type=type(error).__name__,
                    error=str(error)[:300],
                )
                raise
            delay = BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0, 0.5)
            _log(
                logging.WARNING,
                "llm.complete_text.retry",
                model=model,
                attempt=attempt + 1,
                delay_s=round(delay, 2),
                error_type=type(error).__name__,
            )
            await asyncio.sleep(delay)

    raise RuntimeError("unreachable")  # pragma: no cover


def _get_audio_client() -> AsyncOpenAI:
    global _audio_client
    if _audio_client is None:
        settings = get_settings()
        _audio_client = AsyncOpenAI(
            base_url=settings.audio_base_url or settings.llm_base_url,
            api_key=settings.audio_api_key or settings.llm_api_key,
            timeout=settings.llm_timeout,
            max_retries=0,
        )
    return _audio_client


async def transcribe_audio(
    audio_bytes: bytes, *, filename: str, content_type: str, model: str | None = None
) -> str:
    """Transcribe Persian audio through a configurable OpenAI-compatible API."""
    settings = get_settings()
    transcription_model = model or settings.speech_to_text_model
    if not transcription_model:
        raise RuntimeError("SPEECH_TO_TEXT_MODEL must be configured for voice questions")
    if not audio_bytes:
        raise ValueError("audio file is empty")

    client = _get_audio_client()
    async with _get_semaphore():
        response = await client.audio.transcriptions.create(
            model=transcription_model,
            file=(filename, audio_bytes, content_type),
            language="fa",
        )
    text = getattr(response, "text", "")
    if not text or not text.strip():
        raise ValueError("audio transcription returned no text")
    _log(logging.INFO, "llm.transcribe_audio.ok", model=transcription_model)
    return text.strip()


async def close_llm_clients() -> None:
    """Dispose provider HTTP clients during application shutdown."""
    global _client, _embedding_client, _audio_client
    clients = (_client, _embedding_client, _audio_client)
    _client = None
    _embedding_client = None
    _audio_client = None
    for client in clients:
        if client is not None:
            await client.close()


async def vision_json(
    model: str,
    system_prompt: str,
    user_text: str,
    image_png_bytes: bytes,
    image_mime_type: str = "image/png",
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
                    "image_url": {"url": f"data:{image_mime_type};base64,{image_b64}"},
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
