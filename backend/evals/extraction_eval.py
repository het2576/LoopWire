"""Extraction eval: does each extractor succeed when it should, and when it
fails, does it diagnose the *right* reason? (v1's smoke test only checked
success/failure, so a dead link "passed" by being reported as a paywall.)

Successful extractions are cached to evals/.cache/docs/ as stable inputs for
summary_eval.py. No LLM calls.

    uv run python -m evals.extraction_eval
"""

import json
import os
import time
from collections import defaultdict

from app.config import get_settings
from app.url_utils import classify_url
from app.worker import run_extractor
from evals.common import cache_path, load_jsonl, run_dir, write_json


class _Item:
    def __init__(self, url):
        self.url, self.type = url, classify_url(url)


def run(out_dir=None) -> dict:
    out_dir = out_dir or run_dir()
    rows = []
    skipped = []
    settings = get_settings()
    no_proxy_datacenter = bool(os.environ.get("CI")) and not settings.webshare_proxy_username
    for case in load_jsonl("extraction.jsonl"):
        if case.get("residential_ip_only") and no_proxy_datacenter:
            # YouTube blocks datacenter IPs outright; on CI without a proxy this
            # measures the runner's IP, not the extractor. Reported as skipped.
            skipped.append(case["id"])
            print(f"[SKIP] {case['id']:<22} needs a residential IP or proxy")
            continue
        item = _Item(case["url"])
        started = time.perf_counter()
        if item.type == "unsupported":
            result = {"extraction_success": False, "error": "unsupported_source", "clean_text": None, "title": None}
        else:
            result = run_extractor(item)
        latency = round(time.perf_counter() - started, 2)
        words = len((result.get("clean_text") or "").split())
        code = (result.get("error") or "").split(":", 1)[0]

        success_ok = result["extraction_success"] == case["expect_success"]
        if case["expect_success"]:
            diagnosis_ok = success_ok and words >= case.get("min_words", 1)
        else:
            diagnosis_ok = success_ok and code in case["expect_error_in"]
        rows.append({
            "id": case["id"], "type": item.type, "expected_success": case["expect_success"],
            "success": result["extraction_success"], "error": (result.get("error") or "")[:160],
            "words": words, "duration_s": result.get("duration_seconds"), "latency_s": latency,
            "success_match": success_ok, "fully_correct": diagnosis_ok,
        })
        mark = "PASS" if diagnosis_ok else "FAIL"
        print(f"[{mark}] {case['id']:<22} {item.type:<8} success={result['extraction_success']!s:<5} "
              f"words={words:<6} {code or ''}")
        if result["extraction_success"]:
            cache_path("docs", case["url"]).write_text(json.dumps({
                "id": case["id"], "url": case["url"], "type": item.type, "title": result.get("title"),
                "text": result["clean_text"], "duration_seconds": result.get("duration_seconds"),
            }))

    by_type = defaultdict(lambda: [0, 0])
    for r in rows:
        by_type[r["type"]][0] += r["fully_correct"]
        by_type[r["type"]][1] += 1
    summary = {
        "cases": len(rows),
        "skipped": skipped,
        "success_match_rate": round(sum(r["success_match"] for r in rows) / len(rows), 3),
        "fully_correct_rate": round(sum(r["fully_correct"] for r in rows) / len(rows), 3),
        "by_type": {t: f"{a}/{b}" for t, (a, b) in sorted(by_type.items())},
        "rows": rows,
    }
    write_json(out_dir / "extraction.json", summary)
    print(f"\nExtraction: {summary['fully_correct_rate']:.0%} fully correct "
          f"({summary['success_match_rate']:.0%} success/failure match) over {len(rows)} cases")
    return summary


if __name__ == "__main__":
    run()
