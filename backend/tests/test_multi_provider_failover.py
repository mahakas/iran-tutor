from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.core import llm_client
from app.services import ai_gateway, ai_provider_service
from app.services.ai_provider_service import ResolvedRoute


def _route(provider_id: int, model_name: str) -> ResolvedRoute:
    return ResolvedRoute(
        feature_key="chat",
        provider_id=provider_id,
        provider_name=f"provider-{provider_id}",
        provider_type="openai_compatible",
        base_url=f"https://provider-{provider_id}.invalid/v1",
        model_name=model_name,
        temperature=0.2,
        max_tokens=None,
        api_key=f"key-{provider_id}",
        source="route" if provider_id == 1 else "fallback",
    )


@pytest.mark.asyncio
async def test_sessionless_internal_call_resolves_managed_provider_route(monkeypatch):
    candidates = [_route(1, "model-a")]
    seen: list[str] = []

    class SessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    async def resolve(session, feature_key):
        assert session is not None
        seen.append(feature_key)
        return candidates

    monkeypatch.setattr(ai_gateway, "async_session_factory", lambda: SessionContext())
    monkeypatch.setattr(ai_gateway, "resolve_feature_route_chain", resolve)

    result = await ai_gateway._resolve_candidates("embedding", None)

    assert result == candidates
    assert seen == ["embedding"]


@pytest.mark.asyncio
async def test_gateway_tries_ordered_fallback_after_provider_availability_error(monkeypatch):
    monkeypatch.setattr(ai_gateway, "is_provider_failover_error", lambda _error: True)
    candidates = [_route(1, "model-a"), _route(2, "model-b"), _route(3, "model-c")]
    attempted: list[tuple[int, str]] = []

    async def invoke(model: str, route: ResolvedRoute | None):
        assert route is not None
        attempted.append((route.provider_id, model))
        if route.provider_id < 3:
            raise RuntimeError("provider unavailable")
        return "answer from backup"

    selected, model, answer = await ai_gateway._invoke_with_failover(candidates, None, invoke)

    assert attempted == [(1, "model-a"), (2, "model-b"), (3, "model-c")]
    assert selected is candidates[2]
    assert model == "model-c"
    assert answer == "answer from backup"


@pytest.mark.asyncio
async def test_gateway_does_not_fail_over_for_non_availability_error(monkeypatch):
    monkeypatch.setattr(ai_gateway, "is_provider_failover_error", lambda _error: False)
    candidates = [_route(1, "model-a"), _route(2, "model-b")]
    attempted: list[int] = []

    async def invoke(model: str, route: ResolvedRoute | None):
        assert route is not None
        attempted.append(route.provider_id)
        raise ValueError("invalid request")

    with pytest.raises(ValueError, match="invalid request"):
        await ai_gateway._invoke_with_failover(candidates, None, invoke)

    assert attempted == [1]


@pytest.mark.asyncio
async def test_streaming_policy_blocks_provider_switch_after_first_visible_chunk(monkeypatch):
    monkeypatch.setattr(ai_gateway, "is_provider_failover_error", lambda _error: True)
    candidates = [_route(1, "model-a"), _route(2, "model-b")]
    emitted = False
    attempted: list[int] = []

    async def invoke(model: str, route: ResolvedRoute | None):
        nonlocal emitted
        assert route is not None
        attempted.append(route.provider_id)
        emitted = True
        raise RuntimeError("stream dropped after output")

    with pytest.raises(RuntimeError, match="stream dropped"):
        await ai_gateway._invoke_with_failover(
            candidates,
            None,
            invoke,
            can_failover=lambda _error: not emitted,
        )

    assert attempted == [1]


@pytest.mark.asyncio
async def test_provider_context_is_isolated_between_concurrent_tasks():
    async def read_provider(base_url: str, api_key: str):
        with llm_client.use_provider(base_url, api_key):
            await asyncio.sleep(0)
            current = llm_client._provider_override.get()
            assert current is not None
            return current.base_url, current.api_key

    results = await asyncio.gather(
        read_provider("https://a.invalid/v1", "secret-a"),
        read_provider("https://b.invalid/v1", "secret-b"),
    )
    assert results == [
        ("https://a.invalid/v1", "secret-a"),
        ("https://b.invalid/v1", "secret-b"),
    ]
    assert llm_client._provider_override.get() is None


@pytest.mark.asyncio
async def test_route_chain_preserves_order_models_and_skips_native_protocols(monkeypatch):
    providers = {
        1: SimpleNamespace(
            id=1, name="primary", provider_type="openai_compatible",
            base_url="https://primary.invalid/v1", encrypted_api_key="primary-key",
            capabilities=["chat"], is_active=True,
        ),
        2: SimpleNamespace(
            id=2, name="local backup", provider_type="local",
            base_url="http://localhost:11434/v1", encrypted_api_key=None,
            capabilities=["chat"], is_active=True,
        ),
        3: SimpleNamespace(
            id=3, name="native Gemini", provider_type="gemini",
            base_url="https://generativelanguage.googleapis.com", encrypted_api_key="gemini-key",
            capabilities=["chat"], is_active=True,
        ),
    }

    route = SimpleNamespace(
        provider_id=1,
        fallback_provider_ids=[2, 3],
        fallback_provider_id=None,
        model_name="primary-model",
        fallback_model_names=["local-model", "gemini-model"],
        fallback_model_name=None,
        temperature=0.25,
        max_tokens=1024,
    )

    class FakeSession:
        async def get(self, _model, provider_id):
            return providers.get(provider_id)

    async def fake_get_active_route(_session, _feature_key):
        return route

    monkeypatch.setattr(ai_provider_service, "get_active_route", fake_get_active_route)
    monkeypatch.setattr(ai_provider_service, "decrypt_secret", lambda value: value)

    candidates = await ai_provider_service.resolve_feature_route_chain(FakeSession(), "chat")

    assert candidates is not None
    assert [item.provider_id for item in candidates] == [1, 2]
    assert [item.model_name for item in candidates] == ["primary-model", "local-model"]
    assert candidates[1].api_key == "local-no-auth"


def test_route_aware_client_retry_is_delegated_to_gateway():
    with llm_client.use_provider("https://provider.invalid/v1", "key"):
        assert llm_client._is_retryable(RuntimeError("transient")) is False


def test_routed_openai_client_uses_context_endpoint_and_credential(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_client, "AsyncOpenAI", FakeClient)
    llm_client._routed_clients.clear()

    try:
        with llm_client.use_provider("https://provider.invalid/v1", "provider-secret"):
            client = llm_client._get_client()

        assert isinstance(client, FakeClient)
        assert captured["base_url"] == "https://provider.invalid/v1"
        assert captured["api_key"] == "provider-secret"
        assert captured["max_retries"] == 0
    finally:
        llm_client._routed_clients.clear()
