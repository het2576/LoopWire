"""Single entry point for every Gemini call: client reuse, retries, tracing.

Before this, three modules each built their own client, nothing retried a
429/503 (the most common Gemini free-tier failure), and there was no record
of tokens or latency anywhere - so neither cost nor speed could be measured.
Every call now emits one trace record (module logger + optional JSONL file
via LLM_TRACE_PATH, which the eval harness uses to report cost/latency).
"""

import json
import logging
import os
import random
import re
import threading
import time

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger("loopwire.llm")



RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = int(os.environ.get("LLM_MAX_ATTEMPTS", "6"))
MAX_SLEEP_SECONDS = 90.0
_RETRY_DELAY_RE = re.compile(r"retry(?:Delay'?\"?:\s*'?\"?| in )(\d+(?:\.\d+)?)s", re.IGNORECASE)


def _server_retry_delay(exc: Exception) -> float | None:
    """Gemini 429s say exactly how long to wait (RetryInfo.retryDelay); the
    old fixed 2/4/8s backoff ignored it and gave up while still throttled."""
    m = _RETRY_DELAY_RE.search(str(exc))
    return float(m.group(1)) if m else None


class _RateLimiter:
    """Per-model requests-per-minute pacing, opt-in via env
    LLM_RPM_<MODEL> (e.g. LLM_RPM_GEMINI_EMBEDDING_001=90) or LLM_RPM_DEFAULT.
    Free-tier quotas are per minute; pacing beats burst-then-429."""

    def __init__(self):
        self._lock = threading.Lock()
        self._next_slot: dict[str, float] = {}

    def wait(self, model: str) -> None:
        key = "LLM_RPM_" + re.sub(r"[^A-Z0-9]", "_", model.upper())
        rpm = float(os.environ.get(key) or os.environ.get("LLM_RPM_DEFAULT") or 0)
        if rpm <= 0:
            return
        interval = 60.0 / rpm
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot.get(model, now))
            self._next_slot[model] = slot + interval
        if slot > now:
            time.sleep(slot - now)


_limiter = _RateLimiter()

_client: genai.Client | None = None
_client_lock = threading.Lock()
_trace_lock = threading.Lock()


def get_client() -> genai.Client:
    global _client
    with _client_lock:
        if _client is None:
            settings = get_settings()
            if not settings.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY is not set - see SETUP.md")
            # Without a timeout an overloaded model can hang a call
            # indefinitely, holding a worker (and its processing lease).
            timeout_ms = int(float(os.environ.get("LLM_TIMEOUT_SECONDS", "60")) * 1000)
            _client = genai.Client(api_key=settings.gemini_api_key,
                                   http_options=types.HttpOptions(timeout=timeout_ms))
        return _client


def _trace(record: dict) -> None:
    logger.info("llm_call %s", json.dumps(record))
    path = os.environ.get("LLM_TRACE_PATH")
    if path:
        with _trace_lock, open(path, "a") as fh:
            fh.write(json.dumps(record) + "\n")


def _with_retries(op: str, model: str, fn):
    delay = 2.0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        _limiter.wait(model)
        started = time.perf_counter()
        try:
            response = fn()
        except (genai_errors.APIError, httpx.TimeoutException) as exc:
            code = getattr(exc, "code", None) if isinstance(exc, genai_errors.APIError) else 504
            quota = re.search(r"Quota exceeded for metric: ([^,]+), limit: (\d+)", str(exc))
            _trace({"op": op, "model": model, "ok": False, "status": code, "attempt": attempt,
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                    "quota": f"{quota.group(1)}={quota.group(2)}" if quota else None})
            if code == 429 and "PerDay" in str(exc):
                raise  # daily cap: retrying for minutes can't help, fail fast
            if code in RETRYABLE_STATUS and attempt < MAX_ATTEMPTS:
                wait = _server_retry_delay(exc) if code == 429 else None
                wait = min(MAX_SLEEP_SECONDS, (wait + 1.0) if wait else delay * (1 + random.random() * 0.25))
                logger.warning("%s on %s (attempt %d) - retrying in %.0fs", code, model, attempt, wait)
                time.sleep(wait)
                delay = min(delay * 2, MAX_SLEEP_SECONDS)
                continue
            raise
        latency_ms = round((time.perf_counter() - started) * 1000)
        usage = getattr(response, "usage_metadata", None)
        _trace({
            "op": op,
            "model": model,
            "ok": True,
            "attempt": attempt,
            "latency_ms": latency_ms,
            "input_tokens": getattr(usage, "prompt_token_count", None),
            "output_tokens": getattr(usage, "candidates_token_count", None),
            "thinking_tokens": getattr(usage, "thoughts_token_count", None),
        })
        return response
    raise RuntimeError("unreachable")


def _is_legacy_sampling_model(model: str) -> bool:
    """Gemini 2.x honors temperature; 3.x/4.x deprecate temperature/top_p/top_k
    (determinism comes from thinking_level + structured output), and reject
    mixing thinking_level with the legacy thinking_budget."""
    return model.startswith(("gemini-2", "gemini-1"))


def generation_config(system: str, schema, model: str, temperature: float, thinking: str | None):
    kwargs = {"system_instruction": system, "response_mime_type": "application/json", "response_schema": schema}
    if _is_legacy_sampling_model(model):
        kwargs["temperature"] = temperature
    elif thinking:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=types.ThinkingLevel(thinking.upper()))
    return types.GenerateContentConfig(**kwargs)


def generate_structured[T: BaseModel](
    *,
    op: str,
    system: str,
    prompt: str,
    schema: type[T],
    model: str | None = None,
    temperature: float = 0.2,
    thinking: str | None = None,
) -> T:
    """Structured-output generation, parsed and validated into `schema`.
    `temperature` applies to Gemini 2.x only; `thinking` (minimal|low|medium|
    high) to 3.x+."""
    model = model or get_settings().gemini_model
    client = get_client()
    config = generation_config(system, schema, model, temperature, thinking)
    response = _with_retries(
        op,
        model,
        lambda: client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        ),
    )
    parsed = response.parsed
    if parsed is None:
        # Some models return valid JSON text without populating .parsed
        try:
            return schema.model_validate_json(response.text or "")
        except Exception as exc:
            raise ValueError(f"{op}: model did not return parseable structured output: {response.text!r}") from exc
    if isinstance(parsed, schema):
        return parsed
    return schema.model_validate(parsed)


def embed(text: str, *, task_type: str, dimensions: int, model: str) -> list[float]:
    client = get_client()
    response = _with_retries(
        "embed",
        model,
        lambda: client.models.embed_content(
            model=model,
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=dimensions, task_type=task_type),
        ),
    )
    return list(response.embeddings[0].values)
