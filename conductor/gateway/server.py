"""
Inference Gateway — FastAPI server.

Sits between the Conductor orchestrator and the inference backend.
Manages slot orchestration (local), prefix caching, and Ultra Think parallel generation.
Supports local llama-server, Anthropic Claude, OpenAI, and OpenRouter as backends.

Endpoints:
  POST /v1/chat/completions   — OpenAI-compatible proxy
  POST /v1/ultra-think        — Parallel diverse generation
  POST /v1/project/load       — Load project context into template slot (local only)
  POST /v1/project/save       — Persist template KV cache to disk (local only)
  GET  /v1/slots/status       — Current slot utilization
  GET  /v1/metrics            — Throughput and cache stats
"""

from __future__ import annotations

import json
import logging
import os as _os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from .config import GatewayConfig
from .providers import InferenceProvider, create_provider
from .slot_manager import SlotManager
from .ultra_think import UltraThink, UltraThinkResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class ChatCompletionRequest(BaseModel):
    model: str = "conductor"
    messages: list[dict]
    max_tokens: int = 4096
    temperature: float = 1.0
    top_p: float = 0.95
    top_k: int = 40
    stop: list[str] | None = None
    # Gateway extension: pin to a specific slot (local provider only)
    id_slot: int | None = None
    # Langfuse trace propagation: nest gateway spans under conductor's trace
    langfuse_trace_id: str | None = None
    langfuse_parent_span_id: str | None = None
    # Execution lane: "live-chat" (latency-sensitive) or "background-task" (throughput)
    lane: str | None = None


class UltraThinkRequest(BaseModel):
    task_id: str
    prompt: str
    system_prompt: str = ""
    tier: int = 2
    max_tokens: int | None = None
    project_id: str | None = None
    # Langfuse trace propagation: nest ultra-think spans under conductor's trace
    langfuse_trace_id: str | None = None
    langfuse_parent_span_id: str | None = None
    # Execution lane: "live-chat" (latency-sensitive) or "background-task" (throughput)
    lane: str | None = None


class ProjectLoadRequest(BaseModel):
    project_id: str
    layer0_text: str


class ProjectSaveRequest(BaseModel):
    project_id: str


class ProjectRestoreRequest(BaseModel):
    project_id: str
    worker_slot_ids: list[int] | None = None


# ---------------------------------------------------------------------------
# App state
# ---------------------------------------------------------------------------

config = GatewayConfig()
provider: InferenceProvider
slot_manager: SlotManager | None = None
prefix_cache = None
ultra_think: UltraThink
metrics_path: Path

# Gateway auth — shared secret between orchestrator and gateway
_GATEWAY_KEY = _os.environ.get("CONDUCTOR_GATEWAY_KEY", "")


def _check_gateway_auth(authorization: str | None = Header(None)) -> None:
    """Verify gateway requests come from the orchestrator.

    In homelab mode (no key set), all requests are allowed (bound to 127.0.0.1).
    In K8s mode, a shared secret is required.
    Uses FastAPI's Header dependency — works regardless of request body type.
    """
    if not _GATEWAY_KEY:
        return  # No key configured — homelab mode, localhost only
    token = (authorization or "").replace("Bearer ", "")
    if token != _GATEWAY_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

def _sanitize_project_id(pid: str) -> str:
    """Sanitize project_id to prevent path traversal."""
    import re as _re
    cleaned = _re.sub(r"[^a-zA-Z0-9_-]", "", pid)
    if not cleaned or cleaned != pid:
        raise HTTPException(status_code=400, detail=f"Invalid project_id: {pid!r}")
    return cleaned



@asynccontextmanager
async def lifespan(app: FastAPI):
    global provider, slot_manager, prefix_cache, ultra_think, metrics_path

    provider = create_provider(config)

    # Slot management and prefix caching only work with local llama-server
    if config.is_local:
        from .prefix_cache import PrefixCacheManager

        slot_manager = SlotManager(config)
        prefix_cache = PrefixCacheManager(config)
        ultra_think = UltraThink(config, slot_manager, provider)
    else:
        ultra_think = UltraThink(config, None, provider)

    metrics_path = Path(config.metrics_log_path)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Gateway started — provider: %s (local=%s)",
        provider.provider_name,
        config.is_local,
    )
    yield

    await ultra_think.close()
    if slot_manager is not None:
        await slot_manager.close()
    await provider.close()
    logger.info("Gateway shut down")


app = FastAPI(title="Conductor Inference Gateway", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest, _auth: None = Depends(_check_gateway_auth)):
    """OpenAI-compatible endpoint with transparent slot management."""
    start = time.monotonic()

    extra: dict = {}
    acquired = False
    slot_id = req.id_slot
    # Protect template slot — clients cannot pin to it
    if slot_id is not None and config.is_local and slot_id == config.template_slot_id:
        raise HTTPException(status_code=400, detail="Cannot use template slot directly")

    # Slot management only for local provider
    if config.is_local and slot_manager is not None:
        if slot_id is None:
            workers = await slot_manager.acquire_workers(1, lane=req.lane)
            slot_id = workers[0]
            acquired = True
        extra["id_slot"] = slot_id
        extra["cache_prompt"] = True

    try:
        result = await provider.chat_completion(
            messages=req.messages,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            top_p=req.top_p,
            top_k=req.top_k,
            stop=req.stop,
            extra=extra if extra else None,
        )

        elapsed_ms = (time.monotonic() - start) * 1000
        _log_metric("chat_completion", elapsed_ms, result.usage)

        # Return OpenAI-compatible response shape
        return result.raw_response if result.raw_response else {
            "choices": [
                {"message": {"role": "assistant", "content": result.content}}
            ],
            "model": result.model,
            "usage": result.usage,
        }

    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    finally:
        if acquired and slot_manager is not None:
            slot_manager.release_workers([slot_id])  # type: ignore[list-item]


@app.post("/v1/ultra-think")
async def ultra_think_endpoint(req: UltraThinkRequest, _auth: None = Depends(_check_gateway_auth)) -> dict:
    """Parallel diverse generation for Ultra Think pipeline."""
    if req.tier >= 4:
        raise HTTPException(status_code=400, detail="Tier 4 requires decomposition")

    result = await ultra_think.generate(
        task_id=req.task_id,
        prompt=req.prompt,
        system_prompt=req.system_prompt,
        tier=req.tier,
        max_tokens=req.max_tokens,
        project_id=_sanitize_project_id(req.project_id) if req.project_id else None,
    )

    _log_metric(
        "ultra_think",
        result.timing.total_ms,
        {
            "tier": result.tier,
            "candidates": len(result.candidates),
            "errors": len(result.errors),
        },
    )

    return _serialize_ultra_result(result)


@app.post("/v1/project/load")
async def project_load(req: ProjectLoadRequest, _auth: None = Depends(_check_gateway_auth)):
    """Load project context into template slot KV cache (local only)."""
    if not config.is_local or prefix_cache is None:
        return {"action": "skipped", "reason": "Not using local inference provider"}
    action = await prefix_cache.ensure_loaded(  # type: ignore[arg-type]
        project_id=_sanitize_project_id(req.project_id),
        layer0_text=req.layer0_text,
        slot_manager=slot_manager,  # type: ignore[arg-type]
    )
    return {"project_id": req.project_id, "action": action}


@app.post("/v1/project/save")
async def project_save(req: ProjectSaveRequest, _auth: None = Depends(_check_gateway_auth)):
    """Persist current template slot KV cache to NVMe (local only)."""
    if not config.is_local or slot_manager is None:
        raise HTTPException(
            status_code=400,
            detail="Project cache operations are only available with local inference.",
        )
    metric = await slot_manager.save_template(req.project_id)
    return {"project_id": req.project_id, "duration_ms": metric.duration_ms}


@app.post("/v1/project/restore")
async def project_restore(req: ProjectRestoreRequest, _auth: None = Depends(_check_gateway_auth)):
    """Restore template KV cache into worker slots (local only)."""
    if not config.is_local or slot_manager is None:
        raise HTTPException(
            status_code=400,
            detail="Project cache operations are only available with local inference.",
        )
    targets = req.worker_slot_ids or config.worker_slot_ids
    metrics = await slot_manager.restore_workers_parallel(req.project_id, targets)
    return {
        "project_id": req.project_id,
        "restored_slots": targets,
        "duration_ms": [round(m.duration_ms, 1) for m in metrics],
    }


@app.get("/v1/slots/status")
async def slots_status():
    """Current slot utilization."""
    if not config.is_local or slot_manager is None:
        return {
            "provider": provider.provider_name,
            "message": "Slot management is not applicable for API providers.",
        }
    raw = await slot_manager.get_slots_status()
    return {
        "template_slot": config.template_slot_id,
        "worker_slots": config.worker_slot_ids,
        "available_workers": slot_manager.available_worker_count,
        "live_reserved_slots": sorted(slot_manager._live_reserved_ids),
        "shared_slots": sorted(slot_manager._shared_ids),
        "live_waiters": slot_manager.live_waiters,
        "slots": raw,
    }


@app.get("/v1/metrics")
async def metrics():
    """Aggregated metrics."""
    response: dict = {"provider": provider.provider_name}

    if config.is_local and slot_manager is not None:
        slot_metrics = slot_manager.get_metrics()
        response["slot_operations"] = len(slot_metrics)
        response["recent_slot_ops"] = [
            {
                "slot_id": m.slot_id,
                "operation": m.operation,
                "duration_ms": round(m.duration_ms, 1),
                "success": m.success,
            }
            for m in slot_metrics[-20:]
        ]

    if prefix_cache is not None:
        cache_stats = prefix_cache.get_stats()
        response["cache_hits"] = sum(1 for s in cache_stats if s.action == "hit")
        response["cache_misses"] = sum(
            1 for s in cache_stats if s.action in ("miss", "recompute")
        )

    return response


@app.get("/health")
async def health():
    """Health check — pings the inference backend."""
    engine_ok = await provider.health_check()
    response: dict = {
        "gateway": "ok",
        "provider": provider.provider_name,
        "engine": "ok" if engine_ok else "unreachable",
    }
    if config.is_local and slot_manager is not None:
        response["available_workers"] = slot_manager.available_worker_count
    return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_ultra_result(result: UltraThinkResult) -> dict:
    return {
        "task_id": result.task_id,
        "tier": result.tier,
        "candidates": [
            {
                "slot_id": c.slot_id,
                "content": c.content,
                "sampling_params": c.sampling_params,
                "system_prompt_variant": c.system_prompt_variant,
                "tokens_generated": c.tokens_generated,
                "generation_time_ms": round(c.generation_time_ms, 1),
                "tokens_per_second": c.tokens_per_second,
            }
            for c in result.candidates
        ],
        "timing": {
            "slot_restore_ms": round(result.timing.slot_restore_ms, 1),
            "parallel_generation_ms": round(result.timing.parallel_generation_ms, 1),
            "total_ms": round(result.timing.total_ms, 1),
            "prefix_tokens_cached": result.timing.prefix_tokens_cached,
            "suffix_tokens_per_candidate": result.timing.suffix_tokens_per_candidate,
        },
        "errors": result.errors,
    }


def _log_metric(endpoint: str, duration_ms: float, extra: dict) -> None:
    try:
        entry = {
            "endpoint": endpoint,
            "provider": provider.provider_name,
            "duration_ms": round(duration_ms, 1),
            "timestamp": time.time(),
            **extra,
        }
        with open(metrics_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass
