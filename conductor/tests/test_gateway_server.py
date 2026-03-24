"""Tests for Gateway Server — request models, config resolution, and endpoint behavior.

Covers:
- GatewayConfig: provider resolution, API base defaults, model defaults
- ChatCompletionRequest / UltraThinkRequest: Pydantic validation
- Server endpoint integration via TestClient (health, slots/status, metrics)
"""

from __future__ import annotations

import pytest

from gateway.config import GatewayConfig


# ── GatewayConfig Resolution ─────────────────────────────────────


class TestGatewayConfig:

    def test_default_provider_is_local(self):
        config = GatewayConfig()
        assert config.inference_provider == "local"
        assert config.is_local is True

    def test_anthropic_resolved_api_base(self):
        config = GatewayConfig(inference_provider="anthropic")
        assert config.resolved_api_base == "https://api.anthropic.com"

    def test_openai_resolved_api_base(self):
        config = GatewayConfig(inference_provider="openai")
        assert config.resolved_api_base == "https://api.openai.com/v1"

    def test_openrouter_resolved_api_base(self):
        config = GatewayConfig(inference_provider="openrouter")
        assert config.resolved_api_base == "https://openrouter.ai/api/v1"

    def test_custom_api_base_overrides_default(self):
        config = GatewayConfig(
            inference_provider="openai",
            inference_api_base="https://custom.azure.com/v1",
        )
        assert config.resolved_api_base == "https://custom.azure.com/v1"

    def test_local_api_base_empty(self):
        config = GatewayConfig(inference_provider="local")
        assert config.resolved_api_base == ""

    def test_anthropic_default_model(self):
        config = GatewayConfig(inference_provider="anthropic")
        assert "claude" in config.resolved_model

    def test_openai_default_model(self):
        config = GatewayConfig(inference_provider="openai")
        assert config.resolved_model == "gpt-4o"

    def test_local_default_model(self):
        config = GatewayConfig(inference_provider="local")
        assert config.resolved_model == "conductor"

    def test_custom_model_overrides(self):
        config = GatewayConfig(
            inference_provider="anthropic",
            inference_model="claude-opus-4-6-20250929",
        )
        assert config.resolved_model == "claude-opus-4-6-20250929"

    def test_is_local_false_for_api(self):
        config = GatewayConfig(inference_provider="anthropic")
        assert config.is_local is False

    def test_default_worker_slots(self):
        config = GatewayConfig()
        assert config.worker_slot_ids == [1, 2, 3, 4]
        assert config.template_slot_id == 0

    def test_default_generation_settings(self):
        config = GatewayConfig()
        assert config.tier2_candidates == 3
        assert config.tier3_candidates == 5
        assert config.default_max_tokens == 4096
        assert config.generation_timeout_seconds == 300


# ── Request Model Validation ─────────────────────────────────────

from gateway.server import ChatCompletionRequest, UltraThinkRequest


class TestChatCompletionRequest:

    def test_minimal_request(self):
        req = ChatCompletionRequest(
            messages=[{"role": "user", "content": "hello"}]
        )
        assert req.model == "conductor"
        assert req.max_tokens == 4096
        assert req.temperature == 1.0

    def test_full_request(self):
        req = ChatCompletionRequest(
            model="custom",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=2048,
            temperature=0.5,
            top_p=0.9,
            top_k=20,
            stop=["END"],
            id_slot=2,
            langfuse_trace_id="trace-123",
            lane="live-chat",
        )
        assert req.model == "custom"
        assert req.id_slot == 2
        assert req.lane == "live-chat"

    def test_optional_fields_default_none(self):
        req = ChatCompletionRequest(messages=[])
        assert req.stop is None
        assert req.id_slot is None
        assert req.langfuse_trace_id is None


class TestUltraThinkRequest:

    def test_minimal_request(self):
        req = UltraThinkRequest(task_id="t1", prompt="solve this")
        assert req.tier == 2
        assert req.system_prompt == ""
        assert req.max_tokens is None

    def test_tier_range(self):
        req = UltraThinkRequest(task_id="t1", prompt="p", tier=3)
        assert req.tier == 3


# ── Provider Factory ─────────────────────────────────────────────

from gateway.providers import create_provider
from gateway.providers.local import LocalProvider
from gateway.providers.anthropic import AnthropicProvider
from gateway.providers.openai_compat import OpenAICompatProvider


class TestProviderFactory:

    def test_local_provider_creation(self):
        config = GatewayConfig(inference_provider="local")
        p = create_provider(config)
        assert isinstance(p, LocalProvider)
        assert p.supports_slots is True

    def test_anthropic_provider_creation(self):
        config = GatewayConfig(
            inference_provider="anthropic",
            inference_api_key="sk-ant-test",
        )
        p = create_provider(config)
        assert isinstance(p, AnthropicProvider)
        assert p.supports_slots is False

    def test_openai_provider_creation(self):
        config = GatewayConfig(
            inference_provider="openai",
            inference_api_key="sk-test",
        )
        p = create_provider(config)
        assert isinstance(p, OpenAICompatProvider)

    def test_openrouter_uses_openai_compat(self):
        config = GatewayConfig(
            inference_provider="openrouter",
            inference_api_key="sk-or-test",
        )
        p = create_provider(config)
        assert isinstance(p, OpenAICompatProvider)

    def test_unknown_provider_raises(self):
        config = GatewayConfig(inference_provider="unknown_provider")
        with pytest.raises(ValueError, match="Unknown inference_provider"):
            create_provider(config)

    def test_anthropic_without_key_raises(self):
        config = GatewayConfig(inference_provider="anthropic", inference_api_key="")
        with pytest.raises(ValueError, match="inference_api_key is required"):
            create_provider(config)


# ── Prefix Cache ─────────────────────────────────────────────────

from gateway.prefix_cache import PrefixCacheManager


class TestPrefixCacheHashing:

    def test_same_content_same_hash(self):
        h1 = PrefixCacheManager.compute_hash("hello world")
        h2 = PrefixCacheManager.compute_hash("hello world")
        assert h1 == h2

    def test_different_content_different_hash(self):
        h1 = PrefixCacheManager.compute_hash("hello")
        h2 = PrefixCacheManager.compute_hash("world")
        assert h1 != h2

    def test_hash_length(self):
        h = PrefixCacheManager.compute_hash("test content")
        assert len(h) == 16

    def test_cache_validity(self):
        config = GatewayConfig(kv_cache_dir="/tmp/test-cache")
        mgr = PrefixCacheManager(config)
        assert not mgr.has_valid_cache("proj1", "content")
