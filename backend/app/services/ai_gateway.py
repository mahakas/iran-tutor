"""Central AI Gateway — the single entrypoint for every AI call in the app.

Phase 1 of `docs/DARSYAR_AGENT_PACK.md`. Nothing outside this module (and the
low-level `app.core.llm_client` it wraps) may call an LLM, vision, STT, TTS or
embedding provider.

For every call the gateway:

1. resolves the admin-configured provider + model for the feature
   (`feature_model_routes` -> `ai_providers`, with fallback), falling back to the
   legacy `.env` settings when no route is configured;
2. records quota usage (`quota_service.record_ai_usage`). Pre-call quota and
   rate-limit checks (`quota_service.enforce_ai_quota`) are performed by the
   calling layer — API routes and `capability_runtime.enforce_capability_call` —
   so that a single request is never counted twice;
3. performs the call through `app.core.llm_client`;
4. writes one complete `ai_audit_logs` row (prompt, response, citations, tokens,
   cost, latency, status) and increments quota counters.

Audit writes never raise: a logging failure must not break a student answer.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.llm_client import (
    complete_json,
    complete_text,
    embed_texts,
    synthesize_speech,
    stream_text,
    transcribe_audio,
    vision_json,
    use_provider,
    is_provider_failover_error,
)
from app.db.session import async_session_factory
from app.models.governance import AiAuditLog
from app.services import quota_service
from app.services.ai_provider_service import ResolvedRoute, resolve_feature_route_chain

logger = logging.getLogger(__name__)

# Rough USD prices per 1M tokens, used only for the admin cost estimate.
# Intentionally conservative defaults; admins can refine per-provider later.
_PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    "default": (2.50, 10.00),
}

STATUS_SUCCESS = "success"
STATUS_ERROR = "error"
STATUS_BLOCKED = "blocked"
STATUS_FLAGGED = "flagged"


@dataclass
class CallContext:
    """Who/why for one gateway call — everything the audit row needs."""

    feature_key: str
    user_id: str | None = None
    session_id: str | None = None
    skill_id: str | None = None
    book_id: int | None = None
    textbook_strict: bool = False
    citations: list[dict[str, Any]] = field(default_factory=list)
    rag_hit_count: int | None = None


@dataclass
class GatewayResult:
    """Response payload plus the audit metadata the caller may echo back."""

    content: Any
    audit_id: str | None = None
    provider_id: int | None = None
    provider_name: str | None = None
    model_name: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    status: str = STATUS_SUCCESS


def estimate_cost_usd(model_name: str | None, tokens_in: int, tokens_out: int) -> float:
    prompt_price, completion_price = _PRICE_PER_MTOK["default"]
    cost = (tokens_in / 1_000_000) * prompt_price + (tokens_out / 1_000_000) * completion_price
    return round(cost, 6)


def _summarize_messages(messages: Any) -> list[dict[str, Any]]:
    """Best-effort JSON-safe copy of the request messages (images stripped)."""
    if not isinstance(messages, list):
        return []
    out: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        if isinstance(content, list):
            parts: list[dict[str, Any]] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    parts.append({"type": "image_url", "image_url": "[base64 omitted]"})
                elif isinstance(part, dict):
                    parts.append(part)
            content = parts
        out.append({"role": role, "content": content})
    return out


def _citations_payload(citations: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Trim citations down to the fields the admin console needs."""
    trimmed: list[dict[str, Any]] = []
    for citation in citations or []:
        if not isinstance(citation, dict):
            continue
        trimmed.append(
            {
                key: citation.get(key)
                for key in (
                    "book_id",
                    "book_title",
                    "grade_number",
                    "major_code",
                    "branch_titles",
                    "field_titles",
                    "subject_titles",
                    "academic_year_code",
                    "edition_label",
                    "print_year",
                    "publisher",
                    "chapter_number",
                    "chapter_title",
                    "pdf_page_index",
                    "printed_page_number",
                    "citation",
                    "score",
                )
                if key in citation
            }
        )
    return trimmed


async def _resolve_candidates(
    feature_key: str, session: AsyncSession | None
) -> list[ResolvedRoute] | None:
    """Resolve the provider chain, opening a short-lived session for internal calls.

    None means no managed route exists (legacy .env fallback remains available).
    An empty list means a managed route exists but has no usable provider.
    """
    try:
        if session is not None:
            return await resolve_feature_route_chain(session, feature_key)
        async with async_session_factory() as own_session:
            return await resolve_feature_route_chain(own_session, feature_key)
    except Exception:  # noqa: BLE001 - routing lookup failure must be visible, not hide a route
        logger.exception("ai_gateway.route_lookup_failed feature=%s", feature_key)
        raise


async def _invoke_with_failover(
    candidates: list[ResolvedRoute] | None,
    legacy_model: str | None,
    operation: Callable[[str, ResolvedRoute | None], Awaitable[Any]],
    *,
    can_failover: Callable[[Exception], bool] | None = None,
) -> tuple[ResolvedRoute | None, str, Any]:
    """Run one inference operation against an ordered provider chain exactly once per candidate.

    Managed provider calls disable low-level retry loops so this layer can move promptly
    to the next candidate. Only provider availability/authentication responses trigger
    failover; validation and caller errors do not.
    """
    if candidates is None:
        if not legacy_model:
            raise RuntimeError("no model is configured for this feature")
        return None, legacy_model, await operation(legacy_model, None)
    if not candidates:
        raise RuntimeError("the feature route has no active, compatible, credentialed provider")

    last_error: Exception | None = None
    for index, candidate in enumerate(candidates):
        if not candidate.configured or not candidate.base_url or not candidate.model_name:
            continue
        try:
            with use_provider(candidate.base_url, candidate.api_key or "local-no-auth"):
                result = await operation(candidate.model_name, candidate)
            return candidate, candidate.model_name, result
        except Exception as error:  # noqa: BLE001 - classified below
            last_error = error
            allowed = is_provider_failover_error(error)
            if can_failover is not None:
                allowed = allowed and can_failover(error)
            if not allowed or index >= len(candidates) - 1:
                raise
            logger.warning(
                "ai_gateway.provider_failover feature=%s failed_provider_id=%s error_type=%s next_index=%s",
                candidate.feature_key, candidate.provider_id, type(error).__name__, index + 1,
            )
    if last_error is not None:
        raise last_error
    raise RuntimeError("the feature route has no usable provider candidate")


async def _write_audit(
    *,
    ctx: CallContext,
    route: ResolvedRoute | None,
    model_name: str | None,
    messages: Any,
    response_text: str | None,
    tokens_in: int,
    tokens_out: int,
    latency_ms: int,
    status: str,
    error_message: str | None = None,
    flag_reason: str | None = None,
    session: AsyncSession | None = None,
) -> str | None:
    """Persist the audit row; returns its id (or None when logging failed)."""
    audit_feature = ctx.feature_key
    citations = _citations_payload(ctx.citations)
    hit_count = ctx.rag_hit_count if ctx.rag_hit_count is not None else len(citations)

    effective_status = status
    effective_flag = flag_reason
    if (
        effective_status == STATUS_SUCCESS
        and ctx.textbook_strict
        and hit_count == 0
    ):
        effective_status = STATUS_FLAGGED
        effective_flag = effective_flag or "rag_miss_in_textbook_strict_mode"

    record = AiAuditLog(
        user_id=ctx.user_id,
        session_id=ctx.session_id,
        feature_key=audit_feature,
        skill_id=ctx.skill_id,
        provider_id=route.provider_id if route else None,
        model_name=model_name,
        request_messages_json=_summarize_messages(messages),
        response_text=(response_text or "")[:20000] or None,
        rag_citations_json=citations,
        rag_hit_count=hit_count,
        tokens_in=max(0, tokens_in),
        tokens_out=max(0, tokens_out),
        estimated_cost_usd=estimate_cost_usd(model_name, tokens_in, tokens_out),
        latency_ms=max(0, latency_ms),
        status=effective_status,
        error_message=(error_message or "")[:2000] or None,
        flag_reason=effective_flag,
    )
    audit_id: str | None = None
    try:
        if session is not None:
            session.add(record)
            await session.flush()
            audit_id = record.id
        else:
            async with async_session_factory() as own_session:
                own_session.add(record)
                await own_session.commit()
                audit_id = record.id
    except Exception:  # noqa: BLE001 - observability must not break answers
        logger.exception("ai_gateway.audit_write_failed feature=%s", audit_feature)
        return None

    # Quota counters share the audit producer: same transaction when a caller session
    # exists, otherwise a short dedicated session.
    if ctx.user_id:
        try:
            if session is not None:
                await quota_service.record_ai_usage(
                    session,
                    user_id=ctx.user_id,
                    feature_key=audit_feature,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                )
            else:
                async with async_session_factory() as own_session:
                    await quota_service.record_ai_usage(
                        own_session,
                        user_id=ctx.user_id,
                        feature_key=audit_feature,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                    )
                    await own_session.commit()
        except Exception:  # noqa: BLE001
            logger.exception("ai_gateway.quota_record_failed feature=%s", audit_feature)
    return audit_id


async def complete_text_via_gateway(
    *,
    ctx: CallContext,
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float | None = None,
    session: AsyncSession | None = None,
    usage_hook: Callable[[int, int], None] | None = None,
) -> GatewayResult:
    """Plain-text completion with ordered provider failover, quota and audit."""
    settings = get_settings()
    candidates = await _resolve_candidates(ctx.feature_key, session)
    started = time.perf_counter()
    legacy_model = model or settings.tutor_model

    async def invoke(selected_model: str, _candidate: ResolvedRoute | None) -> str:
        return await complete_text(selected_model, messages)

    try:
        route, effective_model, content = await _invoke_with_failover(candidates, legacy_model, invoke)
    except Exception as error:
        await _write_audit(
            ctx=ctx, route=candidates[0] if candidates else None, model_name=legacy_model,
            messages=messages, response_text=None, tokens_in=0, tokens_out=0,
            latency_ms=max(1, int(round((time.perf_counter() - started) * 1000))),
            status=STATUS_ERROR, error_message=f"{type(error).__name__}: {error}", session=session,
        )
        raise

    latency = max(1, int(round((time.perf_counter() - started) * 1000)))
    tokens_in = max(50, sum(len(str(item.get("content", ""))) for item in messages) // 4)
    tokens_out = max(20, len(content) // 4)
    if usage_hook is not None:
        usage_hook(tokens_in, tokens_out)
    audit_id = await _write_audit(
        ctx=ctx, route=route, model_name=effective_model, messages=messages, response_text=content,
        tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency, status=STATUS_SUCCESS, session=session,
    )
    return GatewayResult(
        content=content, audit_id=audit_id, provider_id=route.provider_id if route else None,
        provider_name=route.provider_name if route else None, model_name=effective_model,
        tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency,
    )


async def stream_text_via_gateway(
    *,
    ctx: CallContext,
    messages: list[dict[str, str]],
    on_chunk: Callable[[str], Awaitable[None]],
    model: str | None = None,
    session: AsyncSession | None = None,
    usage_hook: Callable[[int, int], None] | None = None,
) -> GatewayResult:
    """Stream completion; failover is allowed only before the first visible chunk."""
    settings = get_settings()
    candidates = await _resolve_candidates(ctx.feature_key, session)
    started = time.perf_counter()
    legacy_model = model or settings.tutor_model
    emitted = False

    async def guarded_chunk(chunk: str) -> None:
        nonlocal emitted
        emitted = True
        await on_chunk(chunk)

    async def invoke(selected_model: str, _candidate: ResolvedRoute | None) -> str:
        return await stream_text(selected_model, messages, guarded_chunk)

    try:
        route, effective_model, content = await _invoke_with_failover(
            candidates, legacy_model, invoke, can_failover=lambda _error: not emitted
        )
    except Exception as error:
        await _write_audit(
            ctx=ctx, route=candidates[0] if candidates else None, model_name=legacy_model, messages=messages,
            response_text=None, tokens_in=0, tokens_out=0,
            latency_ms=max(1, int(round((time.perf_counter() - started) * 1000))),
            status=STATUS_ERROR, error_message=f"{type(error).__name__}: {error}", session=session,
        )
        raise

    latency = max(1, int(round((time.perf_counter() - started) * 1000)))
    tokens_in = max(50, sum(len(str(item.get("content", ""))) for item in messages) // 4)
    tokens_out = max(20, len(content) // 4)
    if usage_hook is not None:
        usage_hook(tokens_in, tokens_out)
    audit_id = await _write_audit(
        ctx=ctx, route=route, model_name=effective_model, messages=messages, response_text=content,
        tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency, status=STATUS_SUCCESS, session=session,
    )
    return GatewayResult(
        content=content, audit_id=audit_id, provider_id=route.provider_id if route else None,
        provider_name=route.provider_name if route else None, model_name=effective_model,
        tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency,
    )


async def complete_json_via_gateway(
    *,
    ctx: CallContext,
    messages: list[dict[str, str]],
    model: str | None = None,
    session: AsyncSession | None = None,
    usage_hook: Callable[[int, int], None] | None = None,
) -> GatewayResult:
    """Structured JSON completion with ordered provider failover and auditing."""
    settings = get_settings()
    candidates = await _resolve_candidates(ctx.feature_key, session)
    started = time.perf_counter()
    legacy_model = model or settings.tutor_model

    async def invoke(selected_model: str, _candidate: ResolvedRoute | None) -> dict[str, Any]:
        return await complete_json(selected_model, messages)

    try:
        route, effective_model, parsed = await _invoke_with_failover(candidates, legacy_model, invoke)
    except Exception as error:
        await _write_audit(
            ctx=ctx, route=candidates[0] if candidates else None, model_name=legacy_model, messages=messages,
            response_text=None, tokens_in=0, tokens_out=0,
            latency_ms=max(1, int(round((time.perf_counter() - started) * 1000))),
            status=STATUS_ERROR, error_message=f"{type(error).__name__}: {error}", session=session,
        )
        raise

    serialized = json.dumps(parsed, ensure_ascii=False)
    latency = max(1, int(round((time.perf_counter() - started) * 1000)))
    tokens_in = max(50, sum(len(str(item.get("content", ""))) for item in messages) // 4)
    tokens_out = max(30, len(serialized) // 4)
    if usage_hook is not None:
        usage_hook(tokens_in, tokens_out)
    audit_id = await _write_audit(
        ctx=ctx, route=route, model_name=effective_model, messages=messages, response_text=serialized,
        tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency, status=STATUS_SUCCESS, session=session,
    )
    return GatewayResult(
        content=parsed, audit_id=audit_id, provider_id=route.provider_id if route else None,
        provider_name=route.provider_name if route else None, model_name=effective_model,
        tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency,
    )


async def vision_json_via_gateway(
    *,
    ctx: CallContext,
    system_prompt: str,
    user_text: str,
    image_bytes: bytes,
    image_mime_type: str = "image/png",
    model: str | None = None,
    session: AsyncSession | None = None,
    usage_hook: Callable[[int, int], None] | None = None,
) -> GatewayResult:
    """Vision extraction with ordered provider failover and auditing."""
    settings = get_settings()
    candidates = await _resolve_candidates(ctx.feature_key, session)
    legacy_model = model or settings.vision_model_primary
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}]
    started = time.perf_counter()

    async def invoke(selected_model: str, _candidate: ResolvedRoute | None):
        return await vision_json(selected_model, system_prompt, user_text, image_bytes, image_mime_type)

    try:
        route, effective_model, result = await _invoke_with_failover(candidates, legacy_model, invoke)
        parsed, usage = result
    except Exception as error:
        await _write_audit(
            ctx=ctx, route=candidates[0] if candidates else None, model_name=legacy_model, messages=messages,
            response_text=None, tokens_in=0, tokens_out=0,
            latency_ms=max(1, int(round((time.perf_counter() - started) * 1000))),
            status=STATUS_ERROR, error_message=f"{type(error).__name__}: {error}", session=session,
        )
        raise

    latency = max(1, int(round((time.perf_counter() - started) * 1000)))
    tokens_in = int((usage or {}).get("prompt_tokens") or 0)
    tokens_out = int((usage or {}).get("completion_tokens") or 0)
    if usage_hook is not None:
        usage_hook(tokens_in, tokens_out)
    audit_id = await _write_audit(
        ctx=ctx, route=route, model_name=effective_model, messages=messages,
        response_text=json.dumps(parsed, ensure_ascii=False), tokens_in=tokens_in, tokens_out=tokens_out,
        latency_ms=latency, status=STATUS_SUCCESS, session=session,
    )
    return GatewayResult(
        content=parsed, audit_id=audit_id, provider_id=route.provider_id if route else None,
        provider_name=route.provider_name if route else None, model_name=effective_model,
        tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency,
    )


async def transcribe_audio_via_gateway(
    *,
    ctx: CallContext,
    audio_bytes: bytes,
    filename: str,
    content_type: str,
    model: str | None = None,
    session: AsyncSession | None = None,
    usage_hook: Callable[[int, int], None] | None = None,
) -> GatewayResult:
    """Speech-to-text with ordered provider failover; audio bytes are not audited."""
    settings = get_settings()
    candidates = await _resolve_candidates(ctx.feature_key, session)
    legacy_model = model or settings.speech_to_text_model
    messages = [{"role": "user", "content": f"[audio attachment] name={filename} type={content_type} bytes={len(audio_bytes)}"}]
    started = time.perf_counter()

    async def invoke(selected_model: str, _candidate: ResolvedRoute | None) -> str:
        return await transcribe_audio(audio_bytes, filename=filename, content_type=content_type, model=selected_model)

    try:
        route, effective_model, content = await _invoke_with_failover(candidates, legacy_model, invoke)
    except Exception as error:
        await _write_audit(
            ctx=ctx, route=candidates[0] if candidates else None, model_name=legacy_model, messages=messages,
            response_text=None, tokens_in=0, tokens_out=0,
            latency_ms=max(1, int(round((time.perf_counter() - started) * 1000))),
            status=STATUS_ERROR, error_message=f"{type(error).__name__}: {error}", session=session,
        )
        raise

    latency = max(1, int(round((time.perf_counter() - started) * 1000)))
    tokens_in = max(100, len(audio_bytes) // 1024 * 12)
    tokens_out = max(20, len(content) // 4)
    if usage_hook is not None:
        usage_hook(tokens_in, tokens_out)
    audit_id = await _write_audit(
        ctx=ctx, route=route, model_name=effective_model, messages=messages, response_text=content,
        tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency, status=STATUS_SUCCESS, session=session,
    )
    return GatewayResult(
        content=content, audit_id=audit_id, provider_id=route.provider_id if route else None,
        provider_name=route.provider_name if route else None, model_name=effective_model,
        tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency,
    )


async def speech_via_gateway(
    *,
    ctx: CallContext,
    text: str,
    voice: str,
    session: AsyncSession | None = None,
    usage_hook: Callable[[int, int], None] | None = None,
) -> tuple[bytes, GatewayResult]:
    """Text-to-speech with ordered provider failover and auditing."""
    settings = get_settings()
    candidates = await _resolve_candidates(ctx.feature_key, session)
    legacy_model = getattr(settings, "speech_synthesis_model", None)
    messages = [{"role": "user", "content": f"[tts] voice={voice} chars={len(text)} text={text[:500]}"}]
    started = time.perf_counter()

    async def invoke(selected_model: str, candidate: ResolvedRoute | None) -> bytes:
        return await synthesize_speech(
            text, voice=voice, model=selected_model,
            base_url=candidate.base_url if candidate else None,
            api_key=candidate.api_key if candidate else None,
        )

    try:
        route, effective_model, audio = await _invoke_with_failover(candidates, legacy_model, invoke)
    except Exception as error:
        await _write_audit(
            ctx=ctx, route=candidates[0] if candidates else None, model_name=legacy_model, messages=messages,
            response_text=None, tokens_in=0, tokens_out=0,
            latency_ms=max(1, int(round((time.perf_counter() - started) * 1000))),
            status=STATUS_ERROR, error_message=f"{type(error).__name__}: {error}", session=session,
        )
        raise

    latency = max(1, int(round((time.perf_counter() - started) * 1000)))
    tokens_in = max(1, len(text) // 4)
    if usage_hook is not None:
        usage_hook(tokens_in, 0)
    audio_summary = f"[audio {len(audio)} bytes]"
    audit_id = await _write_audit(
        ctx=ctx, route=route, model_name=effective_model, messages=messages, response_text=audio_summary,
        tokens_in=tokens_in, tokens_out=0, latency_ms=latency, status=STATUS_SUCCESS, session=session,
    )
    return audio, GatewayResult(
        content=audio_summary, audit_id=audit_id, provider_id=route.provider_id if route else None,
        provider_name=route.provider_name if route else None, model_name=effective_model,
        tokens_in=tokens_in, tokens_out=0, latency_ms=latency,
    )


async def embed_via_gateway(
    *,
    ctx: CallContext,
    texts: list[str],
    model: str | None = None,
    session: AsyncSession | None = None,
) -> GatewayResult:
    """Embedding generation with ordered provider failover and auditing."""
    settings = get_settings()
    candidates = await _resolve_candidates(ctx.feature_key, session)
    legacy_model = model or settings.embedding_model
    messages = [{"role": "user", "content": f"[embedding] {len(texts)} texts"}]
    started = time.perf_counter()

    async def invoke(selected_model: str, _candidate: ResolvedRoute | None) -> list[list[float]]:
        return await embed_texts(texts, model=selected_model)

    try:
        route, effective_model, vectors = await _invoke_with_failover(candidates, legacy_model, invoke)
    except Exception as error:
        await _write_audit(
            ctx=ctx, route=candidates[0] if candidates else None, model_name=legacy_model, messages=messages,
            response_text=None, tokens_in=0, tokens_out=0,
            latency_ms=max(1, int(round((time.perf_counter() - started) * 1000))),
            status=STATUS_ERROR, error_message=f"{type(error).__name__}: {error}", session=session,
        )
        raise

    latency = max(1, int(round((time.perf_counter() - started) * 1000)))
    tokens_in = max(1, sum(len(item) for item in texts) // 4)
    vector_summary = f"[{len(vectors)} vectors, dim={len(vectors[0]) if vectors else 0}]"
    audit_id = await _write_audit(
        ctx=ctx, route=route, model_name=effective_model, messages=messages, response_text=vector_summary,
        tokens_in=tokens_in, tokens_out=0, latency_ms=latency, status=STATUS_SUCCESS, session=session,
    )
    return GatewayResult(
        content=vectors, audit_id=audit_id, provider_id=route.provider_id if route else None,
        provider_name=route.provider_name if route else None, model_name=effective_model,
        tokens_in=tokens_in, tokens_out=0, latency_ms=latency,
    )


# ---------------------------------------------------------------------------
# Admin-facing helpers
# ---------------------------------------------------------------------------


async def probe_endpoint(
    *,
    base_url: str,
    api_key: str,
    provider_type: str | None = None,
    model: str | None = None,
    run_prompt: bool = True,
    include_models: bool = True,
) -> dict[str, Any]:
    """Live connectivity probe for one OpenAI-compatible endpoint.

    This is the *single* place in the codebase that talks to a provider outside a
    normal gateway call (``/models`` + a tiny ``/chat/completions``). Both admin
    connection tests go through it:

    * ``POST /admin/providers/{id}/test``  → :func:`probe_provider`
    * ``POST /admin/settings/test-ai``     → called directly with a raw key

    The API key is accepted, used for the ``Authorization`` header, and scrubbed
    from every error string before it is returned, so it can never leak to the
    client or the logs.
    """
    import httpx

    base = (base_url or "").strip().rstrip("/")
    result: dict[str, Any] = {
        "ok": False,
        "provider_type": provider_type,
        "base_url": base,
        "models": [],
        "models_count": 0,
        "latency_ms": 0,
        "error": None,
        "prompt_test": None,
    }
    if not base:
        result["error"] = "نشانی پایه برای این ارائه‌دهنده تنظیم نشده است."
        return result

    def _scrub(text: str) -> str:
        cleaned = str(text or "")
        if api_key and len(api_key) >= 4:
            cleaned = cleaned.replace(api_key, "***")
        return cleaned[:280]

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=20.0) as client:
        if include_models:
            try:
                response = await client.get(f"{base}/models", headers=headers)
                result["status_code"] = response.status_code
                if response.status_code < 400:
                    payload = response.json()
                    items = payload.get("data") if isinstance(payload, dict) else payload
                    if isinstance(items, list):
                        ids = {
                            str(item["id"]).strip()
                            for item in items
                            if isinstance(item, dict) and item.get("id")
                        }
                        result["models"] = sorted(ids)[:150]
                        result["models_count"] = len(result["models"])
                    result["ok"] = True
                else:
                    result["error"] = _scrub(response.text or f"HTTP {response.status_code}")
            except Exception as error:  # noqa: BLE001
                result["error"] = _scrub(f"{type(error).__name__}: {error}")
        else:
            result["ok"] = True
        result["latency_ms"] = max(1, int(round((time.perf_counter() - started) * 1000)))

        prompt_model = (model or "").strip()
        if run_prompt:
            if not prompt_model:
                result["prompt_test"] = {
                    "ok": False,
                    "error": "مدلی برای تست پرامپت مشخص نشده است.",
                }
            elif result["ok"] or include_models is False:
                p_started = time.perf_counter()
                try:
                    completion = await client.post(
                        f"{base}/chat/completions",
                        headers={**headers, "Content-Type": "application/json"},
                        json={
                            "model": prompt_model,
                            "messages": [
                                {"role": "user", "content": "فقط یک کلمه فارسی بنویس: سلام"}
                            ],
                            "max_tokens": 24,
                            "temperature": 0,
                        },
                    )
                    p_latency = max(1, int(round((time.perf_counter() - p_started) * 1000)))
                    if completion.status_code >= 400:
                        result["prompt_test"] = {
                            "ok": False,
                            "model": prompt_model,
                            "status_code": completion.status_code,
                            "latency_ms": p_latency,
                            "error": _scrub(completion.text),
                        }
                    else:
                        body = completion.json()
                        reply = ""
                        choices = body.get("choices") if isinstance(body, dict) else None
                        if isinstance(choices, list) and choices:
                            message = choices[0].get("message") if isinstance(choices[0], dict) else None
                            if isinstance(message, dict):
                                reply = str(message.get("content") or "").strip()
                        result["prompt_test"] = {
                            "ok": True,
                            "model": prompt_model,
                            "status_code": completion.status_code,
                            "latency_ms": p_latency,
                            "reply": reply[:160],
                            "usage": body.get("usage") if isinstance(body, dict) else None,
                        }
                        # A backend may expose chat but not /models (404/405).
                        if not result["ok"] and result.get("status_code") in (404, 405):
                            result["ok"] = True
                            result["error"] = None
                except Exception as error:  # noqa: BLE001
                    result["prompt_test"] = {
                        "ok": False,
                        "model": prompt_model,
                        "error": _scrub(f"{type(error).__name__}: {error}"),
                    }
    await _audit_provider_probe(base=base, model=(model or None), result=result)
    return result


async def _audit_provider_probe(*, base: str, model: str | None, result: dict[str, Any]) -> None:
    """Glass-box record of an admin connectivity probe (never stores the key or raw error body)."""
    prompt = result.get("prompt_test") or None
    prompt_ok = bool(prompt and prompt.get("ok"))
    summary = {
        "base_url": base,
        "ok": bool(result.get("ok")),
        "status_code": result.get("status_code"),
        "models_count": int(result.get("models_count") or 0),
        "prompt_ok": prompt_ok if prompt is not None else None,
    }
    try:
        import json

        await _write_audit(
            ctx=CallContext(feature_key="provider_probe", user_id=None, session_id=None),
            route=None,
            model_name=model,
            messages=[{"role": "system", "content": "admin provider connectivity probe"}],
            response_text=json.dumps(summary, ensure_ascii=False),
            tokens_in=0,
            tokens_out=0,
            latency_ms=int(result.get("latency_ms") or 0),
            status=STATUS_SUCCESS if summary["ok"] else STATUS_ERROR,
            error_message=None if summary["ok"] else str(result.get("error") or "probe failed")[:500],
            flag_reason="provider_probe",
        )
    except Exception:  # noqa: BLE001 - observability must not break admin tests
        logger.exception("ai_gateway.provider_probe_audit_failed")


async def probe_provider(
    provider: Any, *, provider_model: str | None = None, run_prompt: bool = True
) -> dict[str, Any]:
    """Live connectivity check for one stored provider (`POST /admin/providers/{id}/test`)."""
    from app.core.crypto import decrypt_secret

    if provider.provider_type not in {"openai", "openai_compatible", "local"}:
        return {
            "ok": False,
            "provider_id": provider.id,
            "provider_type": provider.provider_type,
            "base_url": provider.base_url or "",
            "status_code": None,
            "models_count": 0,
            "latency_ms": 0,
            "error": "Native protocol adapter is not implemented for this provider type yet.",
            "prompt_test": None,
        }

    api_key = decrypt_secret(provider.encrypted_api_key)
    probe = await probe_endpoint(
        base_url=provider.base_url or "",
        api_key=api_key or "",
        provider_type=provider.provider_type,
        model=provider_model,
        run_prompt=run_prompt,
    )
    return {
        "ok": probe["ok"],
        "provider_id": provider.id,
        "provider_type": provider.provider_type,
        "base_url": probe["base_url"],
        "status_code": probe.get("status_code"),
        "models_count": probe["models_count"],
        "latency_ms": probe["latency_ms"],
        "error": probe["error"],
        "prompt_test": probe["prompt_test"],
    }


async def record_decision_audit(
    *,
    feature_key: str,
    user_id: str | None,
    session_id: str | None,
    request_text: str,
    decision: dict[str, Any],
    flag_reason: str | None = None,
    session: AsyncSession | None = None,
    status: str = STATUS_SUCCESS,
) -> str | None:
    """Audit a non-LLM decision (e.g. router heuristic fallback) in `ai_audit_logs`.

    Phase 4 glass-box rule: every router decision is inspectable in /admin, even
    when no model call happened. Never raises.
    """
    import json

    ctx = CallContext(feature_key=feature_key, user_id=user_id, session_id=session_id)
    messages = [{"role": "user", "content": request_text}]
    return await _write_audit(
        ctx=ctx,
        route=None,
        model_name=None,
        messages=messages,
        response_text=json.dumps(decision, ensure_ascii=False),
        tokens_in=0,
        tokens_out=0,
        latency_ms=0,
        status=status,
        flag_reason=flag_reason,
        session=session,
    )
