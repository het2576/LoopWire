"""Recall-grader eval: does the LLM grader agree with hand labels?

28 labeled (question, reference, answer) cases: exact, paraphrase, informal /
Hinglish, rambling-but-right, partial, wrong, vague, keyword stuffing, empty,
and prompt-injection answers. The costly error is a false accept (an
incorrect answer graded "correct"): it inflates retention and schedules the
card too far out, so it's reported separately.

    uv run python -m evals.recall_eval [--model gemini-x]
"""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from app.config import get_settings
from app.recall import GradeResult, grade_answer
from evals.common import cache_path, load_jsonl, run_dir, summarize_trace, traced, write_json

VERDICTS = ["correct", "partial", "incorrect"]


def run(out_dir=None, model: str | None = None) -> dict:
    out_dir = out_dir or run_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = load_jsonl("recall_grading.jsonl")

    grader_model = model or get_settings().gemini_model

    def grade(case):
        key = f"grade|{grader_model}|" + hashlib.sha256(
            json.dumps([case["question"], case["reference"], case["evidence"], case["answer"]]).encode()).hexdigest()
        path = cache_path("grades", key)
        try:
            if path.exists():
                g = GradeResult.model_validate_json(path.read_text())
            else:
                g = grade_answer(case["question"], case["reference"], case["evidence"], case["answer"], model=model)
                path.write_text(g.model_dump_json())
            return {**case, "got": g.verdict, "feedback": g.feedback}
        except Exception as exc:  # noqa: BLE001
            return {**case, "got": "error", "feedback": str(exc)[:200]}

    with traced(out_dir / "trace_recall.jsonl"), ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(grade, cases))

    graded = [r for r in rows if r["got"] != "error"]
    confusion = {e: Counter() for e in VERDICTS}
    by_cat = defaultdict(lambda: [0, 0])
    for r in graded:
        confusion[r["expected"]][r["got"]] += 1
        by_cat[r["category"]][0] += r["got"] == r["expected"]
        by_cat[r["category"]][1] += 1
        if r["got"] != r["expected"]:
            print(f"  MISS {r['id']:<22} expected={r['expected']:<9} got={r['got']:<9} {r['feedback'][:80]}")

    n = len(graded)
    accuracy = sum(r["got"] == r["expected"] for r in graded) / n if n else 0.0
    # adjacent = off by one step (correct<->partial, partial<->incorrect)
    order = {v: i for i, v in enumerate(VERDICTS)}
    severe = sum(1 for r in graded if r["got"] in order and abs(order[r["got"]] - order[r["expected"]]) == 2)
    incorrect_total = sum(confusion["incorrect"].values())
    result = {
        "model": grader_model,
        "cases": len(rows),
        "graded": n,
        "incomplete": len(rows) - n,
        "accuracy": round(accuracy, 3),
        "false_accept_rate": round(confusion["incorrect"]["correct"] / incorrect_total, 3) if incorrect_total else None,
        "severe_errors": severe,
        "injection_resisted": f"{by_cat['injection'][0]}/{by_cat['injection'][1]}",
        "by_category": {c: f"{a}/{b}" for c, (a, b) in sorted(by_cat.items())},
        "confusion_expected_to_got": {e: dict(c) for e, c in confusion.items()},
        "rows": rows,
        "llm_usage": summarize_trace(out_dir / "trace_recall.jsonl"),
    }
    write_json(out_dir / "recall.json", result)
    print(f"Recall grader ({grader_model}): graded {n}/{len(rows)}, accuracy={accuracy:.0%} false_accept={result['false_accept_rate']} "
          f"severe={severe} injection={result['injection_resisted']}")
    print(f"  confusion: {json.dumps(result['confusion_expected_to_got'])}")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    run(model=ap.parse_args().model)
