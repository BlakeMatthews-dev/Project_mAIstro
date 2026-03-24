"""
Extended test suite for the Conductor Inference Gateway.

Tests server endpoints, Langfuse tracer no-op behavior, SlotManager
KV operations, UltraThink dispatch, and all three provider implementations.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from gateway.config import GatewayConfig
from gateway.langfuse_tracer import LangfuseTracer
from gateway.providers.base import CompletionResult, InferenceProvider
from gateway.slot_manager import SlotManager, SlotMetrics
from gateway.ultra_think import (
    DIVERSITY_PROFILES,
    TIER_N,
    UltraThink,
    UltraThinkResult,
)


# ====================================================================
# Helpers / Fixtures
# ====================================================================

_DUMMY_REQUEST = httpx.Request("POST", "http://fake/test")


def _make_response(status_code: int, json_data=None) -> httpx.Response:
    """Create an httpx.Response with a request set (needed for raise_for_status)."""
    resp = httpx.Response(status_code, json=json_data, request=_DUMMY_REQUEST)
    return resp

CANNED_RESULT = CompletionResult(
    content="Hello from mock",
    model="test-model",
    usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    raw_response={
        "choices": [{"message": {"role": "assistant", "content": "Hello from mock"}}],
        "model": "test-model",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    },
)


class FakeProvider(InferenceProvider):
    """A fake provider for testing that records calls."""

    def __init__(self, *, supports_slots_val: bool = False, name: str = "fake"):
        self.calls: list[dict] = []
        self._supports_slots = supports_slots_val
        self._name = name
        self._health = True

    async def chat_completion(self, *, messages, max_tokens=4096,
                              temperature=1.0, top_p=0.95, top_k=40,
                              stop=None, extra=None) -> CompletionResult:
        self.calls.append({
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "extra": extra,
        })
        return CANNED_RESULT

    async def health_check(self) -> bool:
        return self._health

    async def close(self) -> None:
        pass

    @property
    def supports_slots(self) -> bool:
        return self._supports_slots

    @property
    def provider_name(self) -> str:
        return self._name


@pytest.fixture
def api_config():
    """Non-local (API) gateway config."""
    return GatewayConfig(
        inference_provider="openai",
        inference_api_key="sk-test",
        inference_api_base="https://api.openai.com/v1",
    )


@pytest.fixture
def local_config():
    """Local llama-server config."""
    return GatewayConfig(
        inference_provider="local",
        llama_server_url="http://fake:8080",
        template_slot_id=0,
        worker_slot_ids=[1, 2, 3, 4],
    )


# ====================================================================
# 1. Server endpoint tests
# ====================================================================


class TestServerEndpoints:
    """Test FastAPI endpoints via TestClient, mocking the provider layer."""

    @pytest.fixture(autouse=True)
    def _setup_app(self, tmp_path, monkeypatch):
        """Patch the gateway server module globals before importing app."""
        # Disable gateway auth for testing
        monkeypatch.setenv("CONDUCTOR_GATEWAY_KEY", "")

        fake = FakeProvider(name="test-api")
        metrics_file = tmp_path / "metrics" / "gateway.jsonl"

        # We need to patch the module-level globals used by the route handlers
        import gateway.server as srv
        srv._GATEWAY_KEY = ""  # Also set at runtime

        self._orig_provider = getattr(srv, "provider", None)
        self._orig_slot_manager = getattr(srv, "slot_manager", None)
        self._orig_metrics_path = getattr(srv, "metrics_path", None)
        self._orig_prefix_cache = getattr(srv, "prefix_cache", None)
        self._orig_config = srv.config

        srv.provider = fake
        srv.slot_manager = None
        srv.prefix_cache = None
        srv.config = GatewayConfig(
            inference_provider="openai",
            inference_api_key="sk-test",
            metrics_log_path=str(metrics_file),
        )
        srv.metrics_path = metrics_file
        metrics_file.parent.mkdir(parents=True, exist_ok=True)

        # Build UltraThink with the fake provider (API path, no slots)
        srv.ultra_think = UltraThink(srv.config, None, fake)

        self.fake = fake
        self.client = TestClient(srv.app, raise_server_exceptions=False)
        yield

        # Restore originals
        srv.provider = self._orig_provider
        srv.slot_manager = self._orig_slot_manager
        srv.metrics_path = self._orig_metrics_path
        srv.prefix_cache = self._orig_prefix_cache
        srv.config = self._orig_config

    # -- /health --

    def test_health_returns_ok(self):
        resp = self.client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["gateway"] == "ok"
        assert data["provider"] == "test-api"
        assert data["engine"] == "ok"  # FakeProvider returns True

    def test_health_engine_unreachable(self):
        self.fake._health = False
        resp = self.client.get("/health")
        data = resp.json()
        assert data["engine"] == "unreachable"

    # -- /v1/chat/completions --

    def test_chat_completions_openai_shape(self):
        resp = self.client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp.status_code == 200
        data = resp.json()
        # Should have OpenAI-compatible shape
        assert "choices" in data
        assert data["model"] == "test-model"
        assert data["usage"]["prompt_tokens"] == 10

    def test_chat_completions_calls_provider(self):
        self.client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "test"}],
            "temperature": 0.5,
            "max_tokens": 100,
        })
        assert len(self.fake.calls) == 1
        call = self.fake.calls[0]
        assert call["temperature"] == 0.5
        assert call["max_tokens"] == 100

    def test_chat_completions_no_slot_management_for_api(self):
        """API providers should not pass slot params."""
        self.client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "test"}],
        })
        call = self.fake.calls[0]
        assert call["extra"] is None

    # -- /v1/ultra-think --

    def test_ultra_think_rejects_tier_4(self):
        resp = self.client.post("/v1/ultra-think", json={
            "task_id": "t1",
            "prompt": "do something",
            "tier": 4,
        })
        assert resp.status_code == 400
        assert "Tier 4" in resp.json()["detail"]

    def test_ultra_think_rejects_tier_5(self):
        resp = self.client.post("/v1/ultra-think", json={
            "task_id": "t1",
            "prompt": "do something",
            "tier": 5,
        })
        assert resp.status_code == 400

    def test_ultra_think_tier2_returns_3_candidates(self):
        resp = self.client.post("/v1/ultra-think", json={
            "task_id": "t2",
            "prompt": "solve this",
            "tier": 2,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == 3  # TIER_N[2]=3 profiles
        assert len(data["candidates"]) == 3

    def test_ultra_think_tier3_returns_5_candidates(self):
        resp = self.client.post("/v1/ultra-think", json={
            "task_id": "t3",
            "prompt": "solve this",
            "tier": 3,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["candidates"]) == 5

    # -- /v1/project/load --

    def test_project_load_skipped_for_api_provider(self):
        resp = self.client.post("/v1/project/load", json={
            "project_id": "proj1",
            "layer0_text": "context",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "skipped"

    # -- /v1/slots/status --

    def test_slots_status_api_provider_message(self):
        resp = self.client.get("/v1/slots/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "test-api"
        assert "not applicable" in data["message"].lower()

    # -- /v1/metrics --

    def test_metrics_endpoint(self):
        resp = self.client.get("/v1/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "test-api"
        # No slot_operations or cache keys for API provider
        assert "slot_operations" not in data
        assert "cache_hits" not in data


# ====================================================================
# 2. Langfuse tracer no-op tests
# ====================================================================


class TestLangfuseTracerNoOp:
    """All tracer methods should be silent no-ops when Langfuse is unavailable."""

    @pytest.fixture(autouse=True)
    def _reset_langfuse(self):
        """Ensure Langfuse is marked as unavailable."""
        import gateway.langfuse_tracer as lt
        lt._langfuse = None
        lt._initialized = True  # skip init, force None
        yield
        lt._initialized = False
        lt._langfuse = None

    def test_trace_generation_noop(self):
        tracer = LangfuseTracer()
        # Should not raise
        tracer.trace_generation(
            trace_id="t1", name="test", model="m",
            prompt=[{"role": "user", "content": "hi"}],
            completion="hello", usage={"prompt_tokens": 1, "completion_tokens": 1},
        )

    def test_trace_ultra_think_noop(self):
        tracer = LangfuseTracer()
        tracer.trace_ultra_think(
            task_id="t1", tier=2, candidates=[], errors=[], total_ms=100,
        )

    def test_trace_spawn_returns_none(self):
        tracer = LangfuseTracer()
        result = tracer.trace_spawn(
            trace_id="t1", agent_id="a1", role="coder",
            task_id="t1", subtask_id="s1", tier=2,
        )
        assert result is None

    def test_end_spawn_span_noop(self):
        tracer = LangfuseTracer()
        tracer.end_spawn_span(
            trace_id="t1", span_id="s1", success=True,
        )

    def test_trace_cache_event_noop(self):
        tracer = LangfuseTracer()
        tracer.trace_cache_event(
            project_id="p1", action="hit", content_hash="abc",
        )

    def test_score_output_noop(self):
        tracer = LangfuseTracer()
        tracer.score_output(
            trace_id="t1", scores={"accuracy": 0.9}, variant="v1",
        )

    def test_annotate_noop(self):
        tracer = LangfuseTracer()
        tracer.annotate(trace_id="t1", key="k", value="v")

    def test_trace_review_noop(self):
        tracer = LangfuseTracer()
        tracer.trace_review(
            task_id="t1", scores={"quality": 0.8},
            selected_idx=0, accepted=True,
        )

    def test_flush_noop(self):
        tracer = LangfuseTracer()
        tracer.flush()


# ====================================================================
# 3. SlotManager extended tests
# ====================================================================


class TestSlotManagerExtended:
    """Tests for restore_to_worker, save_template, get_slots_status, etc."""

    @pytest.fixture
    def config(self):
        return GatewayConfig(
            llama_server_url="http://fake:8080",
            template_slot_id=0,
            worker_slot_ids=[1, 2, 3, 4],
        )

    @pytest.fixture
    def manager(self, config):
        return SlotManager(config)

    # -- restore_to_worker --

    async def test_restore_to_worker_success(self, manager):
        mock_response = _make_response(200, {"status": "ok"})
        manager._client = AsyncMock()
        manager._client.post = AsyncMock(return_value=mock_response)

        metric = await manager.restore_to_worker("proj1", worker_slot_id=2)
        assert metric.slot_id == 2
        assert metric.operation == "slot_restore"
        assert metric.success is True
        manager._client.post.assert_called_once()

    async def test_restore_to_worker_template_raises(self, manager):
        with pytest.raises(ValueError, match="Cannot restore into template slot"):
            await manager.restore_to_worker("proj1", worker_slot_id=0)

    async def test_restore_to_worker_http_error(self, manager):
        mock_response = _make_response(500, {"error": "internal"})
        manager._client = AsyncMock()
        manager._client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(httpx.HTTPStatusError):
            await manager.restore_to_worker("proj1", worker_slot_id=1)

        # Metric should still be recorded with success=False
        metrics = manager.get_metrics()
        assert len(metrics) == 1
        assert metrics[0].success is False

    # -- save_template --

    async def test_save_template_success(self, manager):
        mock_response = _make_response(200, {"status": "ok"})
        manager._client = AsyncMock()
        manager._client.post = AsyncMock(return_value=mock_response)

        metric = await manager.save_template("proj1")
        assert metric.slot_id == 0
        assert metric.operation == "slot_save"
        assert metric.success is True

    # -- get_slots_status --

    async def test_get_slots_status_returns_data(self, manager):
        slots_data = [{"id": 0, "state": "idle"}, {"id": 1, "state": "busy"}]
        mock_response = _make_response(200, slots_data)
        manager._client = AsyncMock()
        manager._client.get = AsyncMock(return_value=mock_response)

        result = await manager.get_slots_status()
        assert result == slots_data

    async def test_get_slots_status_on_error_returns_empty(self, manager):
        manager._client = AsyncMock()
        manager._client.get = AsyncMock(side_effect=httpx.ConnectError("fail"))

        result = await manager.get_slots_status()
        assert result == []

    # -- get_metrics --

    async def test_get_metrics_returns_copy(self, manager):
        manager._metrics.append(SlotMetrics(slot_id=1, operation="test", duration_ms=10.0))
        metrics = manager.get_metrics()
        assert len(metrics) == 1
        assert metrics[0].slot_id == 1
        # Verify it's a copy
        metrics.clear()
        assert len(manager.get_metrics()) == 1

    # -- Lane-based reservation --

    def test_lane_split(self, manager):
        """Workers should be split into reserved and shared pools."""
        assert manager._live_reserved_ids == {1, 2}
        assert manager._shared_ids == {3, 4}

    async def test_live_lane_acquire_counts_waiters(self, manager):
        assert manager.live_waiters == 0
        workers = await manager.acquire_workers(1, lane="live-chat")
        # Waiter count should be back to 0 after successful acquire
        assert manager.live_waiters == 0
        manager.release_workers(workers)

    async def test_live_lane_timeout_shorter(self, manager):
        """Live-chat lane should use shorter timeout."""
        # Exhaust all workers
        all_w = await manager.acquire_workers(4)
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            await manager.acquire_workers(1, lane="live-chat", timeout=0.2)
        elapsed = time.monotonic() - start
        # Should have timed out in ~0.2s, not the default 300s
        assert elapsed < 1.0
        manager.release_workers(all_w)

    # -- restore_workers_parallel --

    async def test_restore_workers_parallel(self, manager):
        mock_response = _make_response(200, {"status": "ok"})
        manager._client = AsyncMock()
        manager._client.post = AsyncMock(return_value=mock_response)

        metrics = await manager.restore_workers_parallel("proj1", [1, 2])
        assert len(metrics) == 2
        assert all(m.success for m in metrics)


# ====================================================================
# 4. UltraThink tests
# ====================================================================


class TestUltraThink:
    """Test tier dispatch, diversity profiles, and API vs local paths."""

    @pytest.fixture
    def api_ultra(self, api_config):
        fake = FakeProvider(name="api-test")
        return UltraThink(api_config, None, fake), fake

    def test_tier_n_values(self):
        assert TIER_N[1] == 1
        assert TIER_N[2] == 3
        assert TIER_N[3] == 5

    def test_diversity_profiles_count(self):
        assert len(DIVERSITY_PROFILES) >= 5

    def test_diversity_profiles_have_required_keys(self):
        for p in DIVERSITY_PROFILES:
            assert "label" in p
            assert "temperature" in p
            assert "top_p" in p
            assert "suffix" in p

    async def test_tier2_generates_3_candidates(self, api_ultra):
        ut, fake = api_ultra
        result = await ut.generate(
            task_id="t1", prompt="solve", system_prompt="be helpful", tier=2,
        )
        assert isinstance(result, UltraThinkResult)
        assert len(result.candidates) == 3
        assert result.task_id == "t1"
        assert len(fake.calls) == 3

    async def test_tier3_generates_5_candidates(self, api_ultra):
        ut, fake = api_ultra
        result = await ut.generate(
            task_id="t2", prompt="solve", system_prompt="be helpful", tier=3,
        )
        assert len(result.candidates) == 5
        assert len(fake.calls) == 5

    async def test_tier1_generates_1_candidate(self, api_ultra):
        ut, fake = api_ultra
        result = await ut.generate(
            task_id="t3", prompt="solve", system_prompt="be helpful", tier=1,
        )
        assert len(result.candidates) == 1
        assert len(fake.calls) == 1

    async def test_tier4_raises(self, api_ultra):
        ut, _ = api_ultra
        with pytest.raises(ValueError, match="Tier 4"):
            await ut.generate(
                task_id="t4", prompt="solve", system_prompt="be helpful", tier=4,
            )

    async def test_api_path_no_slot_management(self, api_ultra):
        ut, fake = api_ultra
        result = await ut.generate(
            task_id="t5", prompt="solve", system_prompt="test", tier=2,
        )
        # API path uses slot_id=-1
        for c in result.candidates:
            assert c.slot_id == -1
        # No slot restore
        assert result.timing.slot_restore_ms == 0.0

    async def test_api_path_no_extra_slot_params(self, api_ultra):
        ut, fake = api_ultra
        await ut.generate(
            task_id="t6", prompt="solve", system_prompt="test", tier=1,
        )
        # Provider does not support slots, so extra should be empty/None
        for call in fake.calls:
            assert call["extra"] is None or "id_slot" not in call.get("extra", {})

    async def test_candidates_use_different_profiles(self, api_ultra):
        ut, fake = api_ultra
        result = await ut.generate(
            task_id="t7", prompt="solve", system_prompt="test", tier=2,
        )
        temps = [c.sampling_params.get("temperature") for c in result.candidates]
        # Should have 3 different temperatures from first 3 profiles
        assert len(set(temps)) >= 2  # at least 2 unique (conservative=0.7, standard=1.0, exploratory=1.2)

    async def test_system_prompt_variants_are_different(self, api_ultra):
        ut, _ = api_ultra
        result = await ut.generate(
            task_id="t8", prompt="solve", system_prompt="test", tier=2,
        )
        variants = [c.system_prompt_variant for c in result.candidates]
        assert len(set(variants)) >= 2

    async def test_timing_populated(self, api_ultra):
        ut, _ = api_ultra
        result = await ut.generate(
            task_id="t9", prompt="solve", system_prompt="test", tier=2,
        )
        assert result.timing.total_ms > 0
        assert result.timing.parallel_generation_ms >= 0

    async def test_error_handling_in_generation(self, api_config):
        """If a provider call fails, it should be captured as an error."""

        class FailingProvider(FakeProvider):
            async def chat_completion(self, **kwargs):
                raise RuntimeError("boom")

        failing = FailingProvider(name="fail")
        ut = UltraThink(api_config, None, failing)
        result = await ut.generate(
            task_id="te", prompt="solve", system_prompt="test", tier=2,
        )
        assert len(result.errors) == 3
        assert len(result.candidates) == 0
        assert "boom" in result.errors[0]


# ====================================================================
# 5. Anthropic provider tests
# ====================================================================


class TestAnthropicProvider:
    """Test Anthropic provider request formatting and error handling."""

    @pytest.fixture
    def provider(self):
        config = GatewayConfig(
            inference_provider="anthropic",
            inference_api_key="sk-ant-test",
            inference_api_base="https://api.anthropic.com",
        )
        from gateway.providers.anthropic import AnthropicProvider
        return AnthropicProvider(config)

    async def test_system_prompt_extracted(self, provider):
        """System messages should be extracted to top-level 'system' field."""
        anthropic_response = {
            "content": [{"type": "text", "text": "Hello"}],
            "model": "claude-sonnet-4-5-20250929",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        mock_resp = _make_response(200, anthropic_response)

        provider._client = AsyncMock()
        provider._client.post = AsyncMock(return_value=mock_resp)

        result = await provider.chat_completion(
            messages=[
                {"role": "system", "content": "Be helpful"},
                {"role": "user", "content": "Hi"},
            ],
        )
        assert result.content == "Hello"

        # Verify the request body
        call_kwargs = provider._client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert body["system"] == "Be helpful"
        # System message should NOT be in messages list
        for msg in body["messages"]:
            assert msg["role"] != "system"

    async def test_usage_mapping(self, provider):
        """Anthropic usage fields should map to OpenAI format."""
        anthropic_response = {
            "content": [{"type": "text", "text": "ok"}],
            "model": "claude-sonnet-4-5-20250929",
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        mock_resp = _make_response(200, anthropic_response)
        provider._client = AsyncMock()
        provider._client.post = AsyncMock(return_value=mock_resp)

        result = await provider.chat_completion(
            messages=[{"role": "user", "content": "Hi"}],
        )
        assert result.usage["prompt_tokens"] == 100
        assert result.usage["completion_tokens"] == 50
        assert result.usage["total_tokens"] == 150

    async def test_stop_sequences_mapped(self, provider):
        anthropic_response = {
            "content": [{"type": "text", "text": "ok"}],
            "model": "claude-sonnet-4-5-20250929",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
        mock_resp = _make_response(200, anthropic_response)
        provider._client = AsyncMock()
        provider._client.post = AsyncMock(return_value=mock_resp)

        await provider.chat_completion(
            messages=[{"role": "user", "content": "Hi"}],
            stop=["STOP", "END"],
        )
        call_kwargs = provider._client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert body["stop_sequences"] == ["STOP", "END"]

    async def test_http_error_propagates(self, provider):
        mock_resp = _make_response(429, {"error": "rate limit"})
        provider._client = AsyncMock()
        provider._client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(httpx.HTTPStatusError):
            await provider.chat_completion(
                messages=[{"role": "user", "content": "Hi"}],
            )

    def test_supports_slots_false(self, provider):
        assert provider.supports_slots is False

    def test_provider_name(self, provider):
        assert "anthropic" in provider.provider_name

    async def test_health_check_with_key(self, provider):
        assert await provider.health_check() is True

    async def test_health_check_without_key(self):
        config = GatewayConfig(
            inference_provider="anthropic",
            inference_api_key="",
        )
        from gateway.providers.anthropic import AnthropicProvider
        p = AnthropicProvider(config)
        assert await p.health_check() is False


# ====================================================================
# 6. Local provider tests
# ====================================================================


class TestLocalProvider:
    """Test local llama-server provider."""

    @pytest.fixture
    def provider(self):
        config = GatewayConfig(
            inference_provider="local",
            llama_server_url="http://fake:8080",
        )
        from gateway.providers.local import LocalProvider
        return LocalProvider(config)

    async def test_slot_id_in_extra(self, provider):
        """Extra params with id_slot should be passed through."""
        llama_response = {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "model": "conductor",
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        }
        mock_resp = _make_response(200, llama_response)
        provider._client = AsyncMock()
        provider._client.post = AsyncMock(return_value=mock_resp)

        result = await provider.chat_completion(
            messages=[{"role": "user", "content": "Hi"}],
            extra={"id_slot": 2, "cache_prompt": True},
        )
        assert result.content == "ok"

        call_kwargs = provider._client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert body["id_slot"] == 2
        assert body["cache_prompt"] is True

    async def test_cache_prompt_always_set(self, provider):
        """Local provider always sets cache_prompt=True."""
        llama_response = {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "model": "conductor",
            "usage": {},
        }
        mock_resp = _make_response(200, llama_response)
        provider._client = AsyncMock()
        provider._client.post = AsyncMock(return_value=mock_resp)

        await provider.chat_completion(
            messages=[{"role": "user", "content": "Hi"}],
        )
        call_kwargs = provider._client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert body["cache_prompt"] is True

    async def test_health_check_success(self, provider):
        mock_resp = _make_response(200)
        provider._client = AsyncMock()
        provider._client.get = AsyncMock(return_value=mock_resp)
        assert await provider.health_check() is True

    async def test_health_check_failure(self, provider):
        provider._client = AsyncMock()
        provider._client.get = AsyncMock(side_effect=httpx.ConnectError("down"))
        assert await provider.health_check() is False

    def test_supports_slots_true(self, provider):
        assert provider.supports_slots is True

    def test_provider_name(self, provider):
        assert "local" in provider.provider_name


# ====================================================================
# 7. OpenAI-compatible provider tests
# ====================================================================


class TestOpenAICompatProvider:
    """Test OpenAI-compatible provider."""

    @pytest.fixture
    def provider(self):
        config = GatewayConfig(
            inference_provider="openai",
            inference_api_key="sk-test",
            inference_api_base="https://api.openai.com/v1",
        )
        from gateway.providers.openai_compat import OpenAICompatProvider
        return OpenAICompatProvider(config)

    async def test_request_format(self, provider):
        oai_response = {
            "choices": [{"message": {"role": "assistant", "content": "hi"}}],
            "model": "gpt-4o",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_resp = _make_response(200, oai_response)
        provider._client = AsyncMock()
        provider._client.post = AsyncMock(return_value=mock_resp)

        result = await provider.chat_completion(
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=100,
            temperature=0.7,
        )
        assert result.content == "hi"
        assert result.model == "gpt-4o"

        call_kwargs = provider._client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert body["model"] == "gpt-4o"
        assert body["temperature"] == 0.7
        assert body["max_tokens"] == 100

    async def test_does_not_pass_top_k(self, provider):
        """OpenAI-compat should not pass top_k (non-standard)."""
        oai_response = {
            "choices": [{"message": {"role": "assistant", "content": "hi"}}],
            "model": "gpt-4o",
            "usage": {},
        }
        mock_resp = _make_response(200, oai_response)
        provider._client = AsyncMock()
        provider._client.post = AsyncMock(return_value=mock_resp)

        await provider.chat_completion(
            messages=[{"role": "user", "content": "Hello"}],
            top_k=50,
        )
        call_kwargs = provider._client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert "top_k" not in body

    async def test_stop_sequences(self, provider):
        oai_response = {
            "choices": [{"message": {"role": "assistant", "content": ""}}],
            "model": "gpt-4o",
            "usage": {},
        }
        mock_resp = _make_response(200, oai_response)
        provider._client = AsyncMock()
        provider._client.post = AsyncMock(return_value=mock_resp)

        await provider.chat_completion(
            messages=[{"role": "user", "content": "Hi"}],
            stop=["<end>"],
        )
        call_kwargs = provider._client.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert body["stop"] == ["<end>"]

    async def test_http_error_propagates(self, provider):
        mock_resp = _make_response(500, {"error": "internal"})
        provider._client = AsyncMock()
        provider._client.post = AsyncMock(return_value=mock_resp)

        with pytest.raises(httpx.HTTPStatusError):
            await provider.chat_completion(
                messages=[{"role": "user", "content": "Hi"}],
            )

    def test_supports_slots_false(self, provider):
        assert provider.supports_slots is False

    def test_provider_name_includes_type(self, provider):
        assert "openai" in provider.provider_name

    async def test_bearer_token_in_headers(self, provider):
        """Auth header should use Bearer token."""
        headers = provider._client._headers if hasattr(provider._client, '_headers') else {}
        # Check the client was created with the right headers
        # We access the internal headers dict directly
        assert provider._client.headers.get("authorization") == "Bearer sk-test"


# ====================================================================
# 8. Langfuse tracer WITH mocked Langfuse client
# ====================================================================


class TestLangfuseTracerWithClient:
    """Test that tracer methods actually call the Langfuse SDK when available."""

    @pytest.fixture(autouse=True)
    def _setup_langfuse(self):
        import gateway.langfuse_tracer as lt
        self.mock_lf = MagicMock()
        lt._langfuse = self.mock_lf
        lt._initialized = True
        yield
        lt._initialized = False
        lt._langfuse = None

    def test_get_langfuse_returns_client(self):
        import gateway.langfuse_tracer as lt
        assert lt._get_langfuse() is self.mock_lf

    def test_trace_generation_standalone(self):
        tracer = LangfuseTracer()
        mock_trace = MagicMock()
        self.mock_lf.trace.return_value = mock_trace

        tracer.trace_generation(
            trace_id="t1", name="gen-test", model="test-model",
            prompt=[{"role": "user", "content": "hi"}],
            completion="hello",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
            slot_id=1, tier=2, cache_status="hit",
            lane="live-chat", variant="v1",
        )
        # Standalone: creates a trace and then calls generation on it
        self.mock_lf.trace.assert_called()
        mock_trace.generation.assert_called_once()

    def test_trace_generation_nested(self):
        tracer = LangfuseTracer()
        mock_parent = MagicMock()
        mock_span = MagicMock()
        self.mock_lf.trace.return_value = mock_parent
        mock_parent.span.return_value = mock_span

        tracer.trace_generation(
            trace_id="t1", name="gen-test", model="test-model",
            completion="hello",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
            langfuse_trace_id="trace-123",
            langfuse_parent_span_id="span-456",
        )
        mock_parent.span.assert_called_once()
        mock_span.generation.assert_called_once()

    def test_trace_generation_exception_swallowed(self):
        tracer = LangfuseTracer()
        self.mock_lf.trace.side_effect = RuntimeError("boom")
        # Should not raise
        tracer.trace_generation(
            trace_id="t1", name="test", completion="x",
            usage={"prompt_tokens": 1, "completion_tokens": 1},
        )

    def test_trace_ultra_think_standalone(self):
        tracer = LangfuseTracer()
        mock_trace = MagicMock()
        self.mock_lf.trace.return_value = mock_trace

        tracer.trace_ultra_think(
            task_id="ut1", tier=2,
            candidates=[
                {"content": "c1", "prompt_tokens": 5, "completion_tokens": 3, "slot_id": 1, "profile_name": "p1"},
            ],
            errors=["err1"],
            total_ms=100.0,
            lane="background-task",
        )
        self.mock_lf.trace.assert_called()

    def test_trace_ultra_think_nested(self):
        tracer = LangfuseTracer()
        mock_parent = MagicMock()
        mock_span = MagicMock()
        self.mock_lf.trace.return_value = mock_parent
        mock_parent.span.return_value = mock_span

        tracer.trace_ultra_think(
            task_id="ut2", tier=2,
            candidates=[{"content": "c", "prompt_tokens": 1, "completion_tokens": 1}],
            errors=[],
            total_ms=50.0,
            langfuse_trace_id="trace-1",
            langfuse_parent_span_id="span-1",
        )
        mock_parent.span.assert_called_once()
        mock_span.generation.assert_called()

    def test_trace_ultra_think_exception_swallowed(self):
        tracer = LangfuseTracer()
        self.mock_lf.trace.side_effect = RuntimeError("boom")
        tracer.trace_ultra_think(
            task_id="ut3", tier=2, candidates=[], errors=[], total_ms=0,
        )

    def test_trace_spawn_returns_span_id(self):
        tracer = LangfuseTracer()
        mock_trace = MagicMock()
        mock_span = MagicMock()
        mock_span.id = "new-span-id"
        mock_trace.span.return_value = mock_span
        self.mock_lf.trace.return_value = mock_trace

        result = tracer.trace_spawn(
            trace_id="t1", agent_id="a1", role="coder",
            task_id="t1", subtask_id="s1", tier=2,
            parent_span_id="parent-1", lane="live-chat",
            metadata={"extra": "info"},
        )
        assert result == "new-span-id"

    def test_trace_spawn_exception_returns_none(self):
        tracer = LangfuseTracer()
        self.mock_lf.trace.side_effect = RuntimeError("fail")
        result = tracer.trace_spawn(
            trace_id="t1", agent_id="a1", role="coder",
            task_id="t1", subtask_id="s1", tier=2,
        )
        assert result is None

    def test_end_spawn_span(self):
        tracer = LangfuseTracer()
        mock_trace = MagicMock()
        self.mock_lf.trace.return_value = mock_trace

        tracer.end_spawn_span(
            trace_id="t1", span_id="s1", success=True,
            output_preview="some output", duration_ms=42.0,
        )
        mock_trace.span.assert_called_once()

    def test_end_spawn_span_exception_swallowed(self):
        tracer = LangfuseTracer()
        self.mock_lf.trace.side_effect = RuntimeError("fail")
        tracer.end_spawn_span(
            trace_id="t1", span_id="s1", success=False, error="whoops",
        )

    def test_trace_cache_event(self):
        tracer = LangfuseTracer()
        tracer.trace_cache_event(
            project_id="p1", action="hit", content_hash="abc123",
            latency_ms=5.0,
        )
        self.mock_lf.trace.assert_called_once()

    def test_trace_cache_event_exception_swallowed(self):
        tracer = LangfuseTracer()
        self.mock_lf.trace.side_effect = RuntimeError("fail")
        tracer.trace_cache_event(
            project_id="p1", action="miss", content_hash="abc",
        )

    def test_score_output(self):
        tracer = LangfuseTracer()
        tracer.score_output(
            trace_id="t1", span_id="s1",
            scores={"accuracy": 0.9, "quality": 0.8},
            variant="v1",
        )
        assert self.mock_lf.score.call_count == 2

    def test_score_output_exception_swallowed(self):
        tracer = LangfuseTracer()
        self.mock_lf.score.side_effect = RuntimeError("fail")
        tracer.score_output(
            trace_id="t1", scores={"accuracy": 0.9},
        )

    def test_annotate(self):
        tracer = LangfuseTracer()
        mock_trace = MagicMock()
        self.mock_lf.trace.return_value = mock_trace

        tracer.annotate(trace_id="t1", span_id="s1", key="tag", value="important")
        mock_trace.event.assert_called_once()

    def test_annotate_exception_swallowed(self):
        tracer = LangfuseTracer()
        self.mock_lf.trace.side_effect = RuntimeError("fail")
        tracer.annotate(trace_id="t1", key="k", value="v")

    def test_trace_review(self):
        tracer = LangfuseTracer()
        mock_trace = MagicMock()
        mock_trace.id = "trace-review-id"
        self.mock_lf.trace.return_value = mock_trace

        tracer.trace_review(
            task_id="t1",
            scores={"correctness": 8.0, "quality": 7.0},
            selected_idx=0, accepted=True,
            metadata={"extra": "data"},
        )
        self.mock_lf.trace.assert_called_once()
        assert self.mock_lf.score.call_count == 2

    def test_trace_review_exception_swallowed(self):
        tracer = LangfuseTracer()
        self.mock_lf.trace.side_effect = RuntimeError("fail")
        tracer.trace_review(
            task_id="t1", scores={"q": 1.0}, selected_idx=0, accepted=False,
        )

    def test_flush_calls_client(self):
        tracer = LangfuseTracer()
        tracer.flush()
        self.mock_lf.flush.assert_called_once()

    def test_flush_exception_swallowed(self):
        tracer = LangfuseTracer()
        self.mock_lf.flush.side_effect = RuntimeError("fail")
        tracer.flush()


class TestLangfuseInit:
    """Test the _get_langfuse lazy init."""

    def test_init_import_error(self):
        import gateway.langfuse_tracer as lt
        lt._initialized = False
        lt._langfuse = None
        with patch.dict("sys.modules", {"langfuse": None}):
            with patch("builtins.__import__", side_effect=ImportError("no langfuse")):
                result = lt._get_langfuse()
                assert result is None
                assert lt._initialized is True

    def test_init_connection_error(self):
        import gateway.langfuse_tracer as lt
        lt._initialized = False
        lt._langfuse = None
        mock_langfuse_cls = MagicMock()
        mock_langfuse_cls.return_value.auth_check.side_effect = Exception("connection refused")
        with patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=mock_langfuse_cls)}):
            result = lt._get_langfuse()
            assert result is None

    def test_get_observation_parent_with_both_ids(self):
        import gateway.langfuse_tracer as lt
        mock_lf = MagicMock()
        mock_trace = MagicMock()
        mock_lf.trace.return_value = mock_trace

        result = lt._get_observation_parent(mock_lf, "trace-1", "span-1")
        assert result is mock_trace

    def test_get_observation_parent_without_ids(self):
        import gateway.langfuse_tracer as lt
        mock_lf = MagicMock()
        assert lt._get_observation_parent(mock_lf, None, None) is None
        assert lt._get_observation_parent(mock_lf, "trace-1", None) is None

    def test_get_observation_parent_exception(self):
        import gateway.langfuse_tracer as lt
        mock_lf = MagicMock()
        mock_lf.trace.side_effect = RuntimeError("fail")
        result = lt._get_observation_parent(mock_lf, "t", "s")
        assert result is None


# ====================================================================
# 9. Server endpoint tests — local provider mode + auth
# ====================================================================


class TestServerLocalProvider:
    """Test server endpoints with local provider config (slot management)."""

    @pytest.fixture(autouse=True)
    def _setup_local(self, tmp_path):
        import gateway.server as srv

        self._orig_provider = getattr(srv, "provider", None)
        self._orig_slot_manager = getattr(srv, "slot_manager", None)
        self._orig_metrics_path = getattr(srv, "metrics_path", None)
        self._orig_prefix_cache = getattr(srv, "prefix_cache", None)
        self._orig_config = srv.config
        self._orig_gateway_key = srv._GATEWAY_KEY

        fake = FakeProvider(name="test-local", supports_slots_val=True)
        local_cfg = GatewayConfig(
            inference_provider="local",
            llama_server_url="http://fake:8080",
            template_slot_id=0,
            worker_slot_ids=[1, 2, 3, 4],
            metrics_log_path=str(tmp_path / "metrics" / "gateway.jsonl"),
        )
        mock_sm = MagicMock(spec=SlotManager)
        mock_sm.acquire_workers = AsyncMock(return_value=[1])
        mock_sm.release_workers = MagicMock()
        mock_sm.available_worker_count = 4
        mock_sm._live_reserved_ids = {1, 2}
        mock_sm._shared_ids = {3, 4}
        mock_sm.live_waiters = 0
        mock_sm.get_slots_status = AsyncMock(return_value=[{"id": 0}, {"id": 1}])
        mock_sm.get_metrics = MagicMock(return_value=[
            SlotMetrics(slot_id=1, operation="slot_restore", duration_ms=15.0),
        ])
        mock_sm.save_template = AsyncMock(return_value=SlotMetrics(slot_id=0, operation="slot_save", duration_ms=10.0))
        mock_sm.restore_workers_parallel = AsyncMock(return_value=[
            SlotMetrics(slot_id=1, operation="slot_restore", duration_ms=12.0),
            SlotMetrics(slot_id=2, operation="slot_restore", duration_ms=13.0),
        ])

        mock_prefix_cache = MagicMock()
        mock_prefix_cache.ensure_loaded = AsyncMock(return_value="loaded")
        mock_prefix_cache.get_stats = MagicMock(return_value=[])

        srv.provider = fake
        srv.slot_manager = mock_sm
        srv.prefix_cache = mock_prefix_cache
        srv.config = local_cfg
        srv.metrics_path = tmp_path / "metrics" / "gateway.jsonl"
        srv.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        srv.ultra_think = UltraThink(local_cfg, mock_sm, fake)
        srv._GATEWAY_KEY = ""

        self.fake = fake
        self.mock_sm = mock_sm
        self.client = TestClient(srv.app, raise_server_exceptions=False)
        yield

        srv.provider = self._orig_provider
        srv.slot_manager = self._orig_slot_manager
        srv.metrics_path = self._orig_metrics_path
        srv.prefix_cache = self._orig_prefix_cache
        srv.config = self._orig_config
        srv._GATEWAY_KEY = self._orig_gateway_key

    def test_chat_completions_with_slot_management(self):
        resp = self.client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp.status_code == 200
        self.mock_sm.acquire_workers.assert_called()
        self.mock_sm.release_workers.assert_called()

    def test_template_slot_rejected(self):
        import gateway.server as srv
        resp = self.client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "hi"}],
            "id_slot": 0,
        })
        assert resp.status_code == 400

    def test_project_save_local(self):
        resp = self.client.post("/v1/project/save", json={"project_id": "proj1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == "proj1"

    def test_project_restore_local(self):
        resp = self.client.post("/v1/project/restore", json={
            "project_id": "proj1",
            "worker_slot_ids": [1, 2],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["restored_slots"] == [1, 2]

    def test_slots_status_local(self):
        resp = self.client.get("/v1/slots/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["template_slot"] == 0
        assert data["available_workers"] == 4

    def test_metrics_with_local(self):
        resp = self.client.get("/v1/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "slot_operations" in data

    def test_health_with_local(self):
        resp = self.client.get("/health")
        data = resp.json()
        assert "available_workers" in data

    def test_project_load_local(self):
        resp = self.client.post("/v1/project/load", json={
            "project_id": "proj1",
            "layer0_text": "context text",
        })
        assert resp.status_code == 200

    def test_sanitize_project_id_rejects_traversal(self):
        resp = self.client.post("/v1/project/load", json={
            "project_id": "../etc/passwd",
            "layer0_text": "x",
        })
        assert resp.status_code == 400

    def test_chat_provider_error_returns_502(self):
        self.fake.calls = []

        async def failing_chat(**kwargs):
            raise RuntimeError("backend down")

        self.fake.chat_completion = failing_chat
        resp = self.client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp.status_code == 502


class TestServerProjectSaveRestoreNonLocal:
    """Test project save/restore rejection for non-local providers."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        import gateway.server as srv
        self._orig = {
            "provider": getattr(srv, "provider", None),
            "slot_manager": getattr(srv, "slot_manager", None),
            "prefix_cache": getattr(srv, "prefix_cache", None),
            "config": srv.config,
            "metrics_path": getattr(srv, "metrics_path", None),
            "_GATEWAY_KEY": srv._GATEWAY_KEY,
        }
        fake = FakeProvider(name="api-test")
        srv.provider = fake
        srv.slot_manager = None
        srv.prefix_cache = None
        srv.config = GatewayConfig(
            inference_provider="openai",
            metrics_log_path=str(tmp_path / "m" / "gw.jsonl"),
        )
        srv.metrics_path = tmp_path / "m" / "gw.jsonl"
        srv.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        srv.ultra_think = UltraThink(srv.config, None, fake)
        srv._GATEWAY_KEY = ""
        self.client = TestClient(srv.app, raise_server_exceptions=False)
        yield
        for k, v in self._orig.items():
            setattr(srv, k, v)

    def test_project_save_rejected_for_api(self):
        resp = self.client.post("/v1/project/save", json={"project_id": "p"})
        assert resp.status_code == 400

    def test_project_restore_rejected_for_api(self):
        resp = self.client.post("/v1/project/restore", json={"project_id": "p"})
        assert resp.status_code == 400


class TestServerLifespan:
    """Test the lifespan context manager."""

    @pytest.mark.asyncio
    async def test_lifespan_api_provider(self, tmp_path):
        import gateway.server as srv
        from gateway.server import lifespan

        orig_config = srv.config
        srv.config = GatewayConfig(
            inference_provider="openai",
            inference_api_key="sk-test",
            metrics_log_path=str(tmp_path / "metrics" / "gw.jsonl"),
        )
        try:
            async with lifespan(srv.app):
                assert srv.provider is not None
                assert srv.slot_manager is None
                assert srv.ultra_think is not None
                assert srv.metrics_path.parent.exists()
        finally:
            srv.config = orig_config

    @pytest.mark.asyncio
    async def test_lifespan_local_provider(self, tmp_path):
        import gateway.server as srv
        from gateway.server import lifespan

        orig_config = srv.config
        srv.config = GatewayConfig(
            inference_provider="local",
            llama_server_url="http://fake:8080",
            metrics_log_path=str(tmp_path / "metrics" / "gw.jsonl"),
        )
        try:
            async with lifespan(srv.app):
                assert srv.provider is not None
                assert srv.slot_manager is not None
                assert srv.prefix_cache is not None
                assert srv.ultra_think is not None
        finally:
            srv.config = orig_config


class TestGatewayAuth:
    """Test gateway auth header checking."""

    @pytest.fixture(autouse=True)
    def _setup_auth(self, tmp_path):
        import gateway.server as srv
        self._orig_key = srv._GATEWAY_KEY
        srv._GATEWAY_KEY = "secret-key-123"

        fake = FakeProvider(name="test-auth")
        self._orig_provider = getattr(srv, "provider", None)
        self._orig_config = srv.config
        self._orig_metrics = getattr(srv, "metrics_path", None)
        self._orig_prefix = getattr(srv, "prefix_cache", None)
        self._orig_slot = getattr(srv, "slot_manager", None)

        srv.provider = fake
        srv.slot_manager = None
        srv.prefix_cache = None
        srv.config = GatewayConfig(
            inference_provider="openai",
            metrics_log_path=str(tmp_path / "m" / "gw.jsonl"),
        )
        srv.metrics_path = tmp_path / "m" / "gw.jsonl"
        srv.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        srv.ultra_think = UltraThink(srv.config, None, fake)

        self.client = TestClient(srv.app, raise_server_exceptions=False)
        yield

        srv._GATEWAY_KEY = self._orig_key
        srv.provider = self._orig_provider
        srv.config = self._orig_config
        srv.metrics_path = self._orig_metrics
        srv.prefix_cache = self._orig_prefix
        srv.slot_manager = self._orig_slot

    def test_unauthorized_without_key(self):
        resp = self.client.post("/v1/chat/completions", json={
            "messages": [{"role": "user", "content": "hi"}],
        })
        assert resp.status_code == 401

    def test_authorized_with_correct_key(self):
        resp = self.client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer secret-key-123"},
        )
        assert resp.status_code == 200

    def test_unauthorized_with_wrong_key(self):
        resp = self.client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert resp.status_code == 401


# ====================================================================
# 10. SlotManager warm_template test
# ====================================================================


class TestSlotManagerWarmTemplate:
    """Test warm_template HTTP flow."""

    @pytest.fixture
    def config(self):
        return GatewayConfig(
            llama_server_url="http://fake:8080",
            template_slot_id=0,
            worker_slot_ids=[1, 2, 3, 4],
        )

    @pytest.fixture
    def manager(self, config):
        return SlotManager(config)

    async def test_warm_template_success(self, manager):
        mock_resp_chat = _make_response(200, {"choices": [{"message": {"content": "ok"}}]})
        mock_resp_save = _make_response(200, {"status": "ok"})
        manager._client = AsyncMock()
        manager._client.post = AsyncMock(side_effect=[mock_resp_chat, mock_resp_save])

        metric = await manager.warm_template("proj1", "layer0 context text")
        assert metric.operation == "warm_template"
        assert metric.success is True

    async def test_warm_template_failure(self, manager):
        manager._client = AsyncMock()
        manager._client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with pytest.raises(httpx.ConnectError):
            await manager.warm_template("proj1", "text")

        metrics = manager.get_metrics()
        assert len(metrics) == 1
        assert metrics[0].success is False


# ====================================================================
# 11. UltraThink local path test
# ====================================================================


class TestUltraThinkLocal:
    """Test the local provider path (slot-pinned generation)."""

    async def test_generate_local_path(self):
        config = GatewayConfig(
            inference_provider="local",
            llama_server_url="http://fake:8080",
            worker_slot_ids=[1, 2, 3],
        )
        fake_provider = FakeProvider(supports_slots_val=True, name="local-test")
        mock_sm = MagicMock(spec=SlotManager)
        mock_sm.acquire_workers = AsyncMock(return_value=[1, 2, 3])
        mock_sm.release_workers = MagicMock()
        mock_sm.restore_workers_parallel = AsyncMock(return_value=[])

        ut = UltraThink(config, mock_sm, fake_provider)
        result = await ut.generate(
            task_id="t1", prompt="solve", system_prompt="sys", tier=2,
            project_id="proj1",
        )
        assert len(result.candidates) == 3
        mock_sm.acquire_workers.assert_called_once()
        mock_sm.release_workers.assert_called_once()
        mock_sm.restore_workers_parallel.assert_called_once()

    async def test_generate_local_no_project_id(self):
        """Local path without project_id should skip restore."""
        config = GatewayConfig(
            inference_provider="local",
            llama_server_url="http://fake:8080",
            worker_slot_ids=[1, 2, 3],
        )
        fake_provider = FakeProvider(supports_slots_val=True, name="local-test")
        mock_sm = MagicMock(spec=SlotManager)
        mock_sm.acquire_workers = AsyncMock(return_value=[1, 2, 3])
        mock_sm.release_workers = MagicMock()
        mock_sm.restore_workers_parallel = AsyncMock(return_value=[])

        ut = UltraThink(config, mock_sm, fake_provider)
        result = await ut.generate(
            task_id="t1", prompt="solve", system_prompt="sys", tier=2,
        )
        assert len(result.candidates) == 3
        # restore should NOT be called since no project_id
        mock_sm.restore_workers_parallel.assert_not_called()

    async def test_generate_local_with_slot_extra(self):
        config = GatewayConfig(
            inference_provider="local",
            llama_server_url="http://fake:8080",
            worker_slot_ids=[1],
        )
        fake_provider = FakeProvider(supports_slots_val=True, name="local-test")
        mock_sm = MagicMock(spec=SlotManager)
        mock_sm.acquire_workers = AsyncMock(return_value=[1])
        mock_sm.release_workers = MagicMock()

        ut = UltraThink(config, mock_sm, fake_provider)
        result = await ut.generate(
            task_id="t2", prompt="solve", system_prompt="sys", tier=1,
        )
        assert len(result.candidates) == 1
        # Should have passed slot ID via extra
        call = fake_provider.calls[0]
        assert call["extra"]["id_slot"] == 1
