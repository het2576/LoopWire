"""Shared eval plumbing: datasets, caching, judge-model resolution, tracing."""

import datetime as dt
import hashlib
import json
import os
import re
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

from app.config import get_settings

# Free-tier pacing for eval runs (override via env). Embeddings: documented
# 100 RPM; generation models: conservative default under the free-tier RPM.
os.environ.setdefault("LLM_RPM_GEMINI_EMBEDDING_001", "90")
os.environ.setdefault("LLM_RPM_DEFAULT", "9")

ROOT = Path(__file__).resolve().parent
DATASETS = ROOT / "datasets"
CACHE = ROOT / ".cache"
RESULTS = ROOT / "results"


def load_jsonl(name: str) -> list[dict]:
    with open(DATASETS / name) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def cache_path(kind: str, key: str, suffix: str = ".json") -> Path:
    d = CACHE / kind
    d.mkdir(parents=True, exist_ok=True)
    return d / (hashlib.sha256(key.encode()).hexdigest()[:24] + suffix)


def run_dir() -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    d = RESULTS / stamp
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, default=str))


@contextmanager
def traced(path: Path):
    """Route every app.llm call's trace record into `path` for this block."""
    previous = os.environ.get("LLM_TRACE_PATH")
    os.environ["LLM_TRACE_PATH"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("LLM_TRACE_PATH", None)
        else:
            os.environ["LLM_TRACE_PATH"] = previous


def summarize_trace(path: Path) -> dict:
    """Per (op, model): calls, failures, retries, tokens, p50/p95 latency."""
    if not path.exists():
        return {}
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for line in path.read_text().splitlines():
        rec = json.loads(line)
        groups[(rec["op"], rec["model"])].append(rec)
    out = {}
    for (op, model), recs in sorted(groups.items()):
        ok = [r for r in recs if r["ok"]]
        lat = sorted(r["latency_ms"] for r in ok)

        def pct(p, lat=lat):
            return lat[min(len(lat) - 1, int(p * len(lat)))] if lat else None

        out[f"{op}@{model}"] = {
            "calls": len(ok),
            "failed_attempts": len(recs) - len(ok),
            "input_tokens": sum(r.get("input_tokens") or 0 for r in ok),
            "output_tokens": sum(r.get("output_tokens") or 0 for r in ok),
            "thinking_tokens": sum(r.get("thinking_tokens") or 0 for r in ok),
            "latency_p50_ms": pct(0.5),
            "latency_p95_ms": pct(0.95),
        }
    return out


_FLASH_RE = re.compile(r"^gemini-(\d+(?:\.\d+)?)-flash(?:-preview)?(?:-[\d-]+)?$")


def available_models() -> list[str]:
    from app.llm import get_client

    names = []
    for m in get_client().models.list():
        actions = getattr(m, "supported_actions", None) or []
        if "generateContent" in actions:
            names.append(m.name.removeprefix("models/"))
    return sorted(names)


def resolve_judge_model() -> str:
    """EVAL_JUDGE_MODEL if set; otherwise the newest generally-available
    Gemini Flash the key can access that isn't the model under test.
    Never guesses an id - it picks from the live model list."""
    settings = get_settings()
    if settings.eval_judge_model:
        return settings.eval_judge_model
    candidates = []
    for name in available_models():
        m = _FLASH_RE.match(name)
        if m and "lite" not in name and name != settings.gemini_model:
            candidates.append((float(m.group(1)), "preview" not in name, name))
    if not candidates:
        raise RuntimeError("No Gemini Flash judge model available - set EVAL_JUDGE_MODEL")
    candidates.sort()
    return candidates[-1][2]
