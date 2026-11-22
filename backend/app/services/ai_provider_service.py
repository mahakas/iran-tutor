"""Encrypted AI-provider vault and per-feature model routing (Phase 1, Rule 2).

Only admins touch these records. Secrets are encrypted with
`app.core.crypto` and are never serialized in plaintext.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_secret, encrypt_secret, mask_api_key
from app.models.governance import AiProvider, FeatureModelRoute

logger = logging.getLogger(__name__)

PROVIDER_TYPES: tuple[str, ...] = (
    "openai",
    "anthropic",
    "gemini",
    "openai_compatible",
    "local",
)

PROVIDER_CAPABILITIES: tuple[str, ...] = ("chat", "vision", "stt", "tts", "embedding")

# Feature keys the admin can route models for (Phase 1 scope; extended in later phases).
ROUTABLE_FEATURE_KEYS: tuple[str, ...] = (
    "chat",
    "solve",
    "quiz",
    "vision_ocr",
    "stt",
    "embedding",
    "flashcards",
    "ingest_ocr",
    "memory",
    "intent_router",
    "immersive_reader",
    "deep_solve",
    "quiz_validator",
    "learning_notebook",
    "web_visualize",
    "living_book",
    "audio_tts",
)


@dataclass(frozen=True)
class ResolvedRoute:
    """An effective provider+model binding for one feature."""

    feature_key: str
    provider_id: int | None
    provider_name: str | None
    provider_type: str | None
    base_url: str | None
    model_name: str | None
    temperature: float
    max_tokens: int | None
    api_key: str | None
    source: str  # "route" | "fallback" | "unset"

    @property
    def configured(self) -> bool:
        return bool(self.model_name and self.base_url)


def validate_provider_type(provider_type: str) -> str:
    if provider_type not in PROVIDER_TYPES:
        raise ValueError(f"provider_type must be one of {', '.join(PROVIDER_TYPES)}")
    return provider_type


def normalize_capabilities(raw: list[str] | None) -> list[str]:
    """Keep only known capability names, preserving order and dropping duplicates."""
    out: list[str] = []
    for item in raw or []:
        cleaned = str(item).strip().lower()
        if cleaned in PROVIDER_CAPABILITIES and cleaned not in out:
            out.append(cleaned)
    return out


def serialize_provider(provider: AiProvider) -> dict[str, Any]:
    """Serialize a provider for the API.

    The stored secret is decrypted only to produce the mask, and is never returned:
    `api_key` is always `None` and exists solely so the UI can tell "unchanged" apart
    from "cleared". There is deliberately no `reveal` option — no endpoint may ever
    echo a plaintext key back to a client.
    """
    return {
        "id": provider.id,
        "name": provider.name,
        "provider_type": provider.provider_type,
        "base_url": provider.base_url,
        "capabilities": list(provider.capabilities or []),
        "is_active": provider.is_active,
        "has_api_key": bool(provider.encrypted_api_key),
        "api_key_masked": mask_api_key(decrypt_secret(provider.encrypted_api_key)),
        "api_key": None,
        "last_test_status": provider.last_test_status,
        "last_test_latency_ms": provider.last_test_latency_ms,
        "last_test_at": provider.last_test_at.isoformat() if provider.last_test_at else None,
        "created_at": provider.created_at.isoformat() if provider.created_at else None,
        "updated_at": provider.updated_at.isoformat() if provider.updated_at else None,
    }


def set_provider_api_key(provider: AiProvider, raw_key: str | None) -> None:
    """Encrypt and store, or clear, a provider key. Blank input keeps the old key."""
    if raw_key is None:
        return
    if not raw_key.strip():
        return
    provider.encrypted_api_key = encrypt_secret(raw_key)


def serialize_route(route: FeatureModelRoute) -> dict[str, Any]:
    return {
        "id": route.id,
        "feature_key": route.feature_key,
        "provider_id": route.provider_id,
        "model_name": route.model_name,
        "temperature": route.temperature,
        "max_tokens": route.max_tokens,
        "fallback_provider_id": route.fallback_provider_id,
        "fallback_model_name": route.fallback_model_name,
        "fallback_provider_ids": list(route.fallback_provider_ids or []),
        "fallback_model_names": list(route.fallback_model_names or []),
        "is_active": route.is_active,
    }


async def get_active_route(session: AsyncSession, feature_key: str) -> FeatureModelRoute | None:
    return await session.scalar(
        select(FeatureModelRoute)
        .where(
            FeatureModelRoute.feature_key == feature_key,
            FeatureModelRoute.is_active.is_(True),
        )
        .order_by(FeatureModelRoute.id.desc())
    )


def _required_capability(feature_key: str) -> str | None:
    if feature_key in {"vision_ocr", "ingest_ocr"}:
        return "vision"
    if feature_key == "stt":
        return "stt"
    if feature_key == "audio_tts":
        return "tts"
    if feature_key == "embedding":
        return "embedding"
    return "chat"


async def resolve_feature_route_chain(
    session: AsyncSession, feature_key: str
) -> list[ResolvedRoute] | None:
    """Return ordered, usable provider candidates for one feature.

    None means that no admin route exists (callers may use legacy .env settings).
    An empty list means a route exists but none of its providers is usable.
    Native Anthropic/Gemini protocols are intentionally not sent through the
    OpenAI-compatible client; they need dedicated adapters before they can be routed.
    """
    route = await get_active_route(session, feature_key)
    if route is None:
        return None

    provider_ids = [route.provider_id]
    fallback_ids = list(route.fallback_provider_ids or [])
    if route.fallback_provider_id is not None:
        fallback_ids.append(route.fallback_provider_id)
    for provider_id in fallback_ids:
        if provider_id not in provider_ids:
            provider_ids.append(provider_id)

    model_names = [route.model_name]
    configured_fallback_models = list(route.fallback_model_names or [])
    for index, provider_id in enumerate(provider_ids[1:]):
        configured_name = (
            str(configured_fallback_models[index]).strip()
            if index < len(configured_fallback_models)
            else ""
        )
        if configured_name:
            model_names.append(configured_name)
        elif provider_id == route.fallback_provider_id and route.fallback_model_name:
            model_names.append(route.fallback_model_name)
        else:
            model_names.append(route.model_name)

    required = _required_capability(feature_key)
    candidates: list[ResolvedRoute] = []
    for index, provider_id in enumerate(provider_ids):
        provider = await session.get(AiProvider, provider_id)
        if provider is None or not provider.is_active:
            continue
        if provider.provider_type not in {"openai", "openai_compatible", "local"}:
            logger.warning(
                "ai_route.provider_protocol_unsupported feature=%s provider_id=%s provider_type=%s",
                feature_key, provider.id, provider.provider_type,
            )
            continue
        capabilities = set(provider.capabilities or [])
        if required and capabilities and required not in capabilities:
            continue
        api_key = decrypt_secret(provider.encrypted_api_key)
        if not provider.base_url:
            continue
        if provider.provider_type != "local" and not api_key:
            continue
        candidates.append(
            ResolvedRoute(
                feature_key=feature_key,
                provider_id=provider.id,
                provider_name=provider.name,
                provider_type=provider.provider_type,
                base_url=provider.base_url,
                model_name=model_names[index],
                temperature=route.temperature,
                max_tokens=route.max_tokens,
                api_key=api_key or "local-no-auth",
                source="route" if index == 0 else "fallback",
            )
        )

    if not candidates:
        logger.warning(
            "ai_route.no_usable_provider feature=%s primary_provider_id=%s",
            feature_key, route.provider_id,
        )
    return candidates


async def resolve_feature_route(session: AsyncSession, feature_key: str) -> ResolvedRoute | None:
    """Backward-compatible single-route resolver; returns the first usable candidate."""
    candidates = await resolve_feature_route_chain(session, feature_key)
    return candidates[0] if candidates else None
