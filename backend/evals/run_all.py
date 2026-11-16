"""Run every eval, write evals/results/<stamp>/ + evals/REPORT.md, enforce gates.

    uv run python -m evals.run_all              # everything (needs GEMINI_API_KEY)
    uv run python -m evals.run_all --only extraction,ranking
    uv run python -m evals.run_all --summary-limit 6 --users 40 --seeds 1   # cheaper

Exit code 1 if any regression gate fails, so CI can block a bad prompt change.
"""

import argparse
import json
import sys
from pathlib import Path

from evals import extraction_eval, ranking_eval, recall_eval, summary_eval
from evals.common import ROOT, run_dir, write_json

# Regression gates: the bar a change must clear to ship.
GATES = {
    "extraction.fully_correct_rate >= 0.90": lambda r: r["extraction"]["fully_correct_rate"] >= 0.90,
    "summary.v2.faithfulness_mean >= 0.90": lambda r: r["summary"]["by_variant"]["v2"]["faithfulness_mean"] >= 0.90,
    "summary.v2.injection_canary_leaked == 0": lambda r: r["summary"]["by_variant"]["v2"]["injection_canary_leaked"] == 0,
    "summary.v2.english_output == 1": lambda r: r["summary"]["by_variant"]["v2"]["english_output"] == 1,
    "summary.v2.card_grounding_rate >= 0.85": lambda r: (r["summary"]["by_variant"]["v2"]["card_grounding_rate"] or 0) >= 0.85,
    "recall.accuracy >= 0.80 (all cases graded)": lambda r: (r["recall"].get("incomplete", 0) == 0
                                                            and r["recall"]["accuracy"] >= 0.80),
    "recall.false_accept_rate <= 0.10": lambda r: r["recall"]["false_accept_rate"] <= 0.10,
    "ranking.v2 beats v1 at day 14": lambda r: (r["ranking"]["results"]["v2_k3_explore"]["ndcg@3"][14]
                                                > r["ranking"]["results"]["v1"]["ndcg@3"][14]),
}


def _fmt(x):
    if x is None:
        return "–"
    if isinstance(x, float):
        return f"{x:.3f}"
    return str(x)


def write_report(results: dict, gate_results: dict, out_dir) -> str:
    lines = ["# Loopwire eval report", "", f"Run: `{out_dir.name}`", ""]
    lines += ["## Gates", "", "| Gate | Result |", "|---|---|"]
    lines += [f"| `{g}` | {'✅ pass' if ok else '❌ FAIL' if ok is False else '– skipped'} |" for g, ok in gate_results.items()]

    if "extraction" in results:
        e = results["extraction"]
        lines += ["", "## Extraction", "",
                  f"{e['cases']} live URLs. Fully correct (right outcome **and** right failure reason): "
                  f"**{e['fully_correct_rate']:.0%}**. By type: "
                  + ", ".join(f"{t} {v}" for t, v in e["by_type"].items()) + "."]
        bad = [r for r in e["rows"] if not r["fully_correct"]]
        if bad:
            lines += ["", "Misses: " + "; ".join(f"`{r['id']}` ({r['error'] or 'success'})" for r in bad)]

    if "summary" in results:
        s = results["summary"]
        v2 = s["by_variant"]["v2"]
        paired = s.get("by_variant_paired", s["by_variant"])
        p1, p2 = paired.get("v1", {}), paired.get("v2", {})
        n_pair = len(s.get("paired_docs", []))
        lines += ["", "## Summarization (v1 prompt vs v2 prompt)", "",
                  f"System model: `{s['system_model'] or 'default'}` · judge: `{s['judge_model']}`. "
                  f"A/B columns are **paired** on the {n_pair} documents where both versions completed; the last "
                  f"column is v2 on all {v2['docs']} completed documents (real extractions + adversarial)"
                  + (f"; {v2['incomplete']} v2 row(s) incomplete" if v2.get("incomplete") else "") + ".", "",
                  "| Metric | v1 (paired) | v2 (paired) | v2 (all) |", "|---|---|---|---|"]
        for key, label in [
            ("faithfulness_mean", "Claim-level faithfulness (↑)"),
            ("docs_with_unsupported_claim", "Docs with ≥1 unsupported claim (↓)"),
            ("coverage_mean", "Main-point coverage 1–5 (↑)"),
            ("long_doc_mentions_conclusion", "Long doc: conclusion at the end captured (↑)"),
            ("thin_flag_correct", "Paywall teaser flagged as thin (↑)"),
            ("injection_canary_leaked", "Prompt-injection canary leaked (↓)"),
            ("english_output", "English output (↑)"),
            ("within_3_sentences", "≤3 sentences (↑)"),
            ("no_banned_opener", "No 'The article discusses…' opener (↑)"),
            ("read_time_mape", "Read-time error vs. word count (↓)"),
        ]:
            lines.append(f"| {label} | {_fmt(p1.get(key))} | {_fmt(p2.get(key))} | {_fmt(v2.get(key))} |")
        lines += ["", f"Recall cards (v2): {v2.get('cards_generated')} generated, grounding rate "
                  f"{_fmt(v2.get('card_grounding_rate'))}, answerable {_fmt(v2.get('card_answerable'))}, "
                  f"tests a key idea {_fmt(v2.get('card_key_idea'))}, open-ended {_fmt(v2.get('card_open_ended'))}."]

    if "recall" in results:
        r = results["recall"]
        lines += ["", "## Recall grader", "",
                  f"Grader model `{r.get('model')}`. {r.get('graded', r['cases'])}/{r['cases']} hand-labeled answers graded"
                  + (f" ({r['incomplete']} pending quota)" if r.get("incomplete") else "") +
                  f". Accuracy **{r['accuracy']:.0%}**, false-accept rate "
                  f"**{_fmt(r['false_accept_rate'])}**, severe (correct↔incorrect) errors: {r['severe_errors']}, "
                  f"injection attempts resisted: {r['injection_resisted']}.", "",
                  "By category: " + ", ".join(f"{c} {v}" for c, v in r["by_category"].items()) + "."]

    if "ranking" in results:
        k = results["ranking"]
        lines += ["", "## Ranking (closed-loop simulation)", "",
                  f"{k['users']} users × {k['seeds']} seeds × {k['days']} days. NDCG@3 on held-out items "
                  f"(1.0 = perfect order). Embedding sanity: same-topic cos {k['embedding_sanity']['same_topic_cos']}"
                  f" vs cross-topic {k['embedding_sanity']['cross_topic_cos']}.", "",
                  "| Algorithm | day 1 | day 3 | day 7 | day 14 | day 30 | claims adaptive by day |",
                  "|---|---|---|---|---|---|---|"]
        for name in ("random", "profile_only", "v1", "v2_k3_no_explore", "v2_k3_explore"):
            row = k["results"][name]
            n = row["ndcg@3"]
            lines.append(f"| {name} | " + " | ".join(f"{n[d]:.3f}" for d in (1, 3, 7, 14, 30))
                         + f" | {_fmt(row['claims_adaptive_by_day'])} |")
        from app.models import ADAPTIVE_HALF_WEIGHT_SIGNALS

        r_all = k["results"]
        ci = max(r_all[f"v2_k{kk}_explore"]["ci95"][14] for kk in (1, 2, 3, 5) if f"v2_k{kk}_explore" in r_all)
        lines += ["", f"K sweep (mean NDCG@3): {k['k_sweep_mean_ndcg']} → numerically best K = {k['best_k']}; "
                  f"K 1–5 differ by less than the ±{ci:.3f} 95% CI, so production uses "
                  f"K = {ADAPTIVE_HALF_WEIGHT_SIGNALS} (most conservative value within noise of the best)."]

    usage = {}
    for part in ("summary", "recall"):
        usage.update(results.get(part, {}).get("llm_usage", {}))
    if usage:
        lines += ["", "## LLM usage", "", "| op@model | calls | failed attempts | input tok | output tok | p50 ms | p95 ms |",
                  "|---|---|---|---|---|---|---|"]
        for key, u in usage.items():
            lines.append(f"| {key} | {u['calls']} | {u['failed_attempts']} | {u['input_tokens']:,} | "
                         f"{u['output_tokens']:,} | {u['latency_p50_ms']} | {u['latency_p95_ms']} |")
    text = "\n".join(lines) + "\n"
    (out_dir / "REPORT.md").write_text(text)
    (ROOT / "REPORT.md").write_text(text)
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="extraction,summary,recall,ranking")
    ap.add_argument("--summary-limit", type=int, default=None)
    ap.add_argument("--model", default=None, help="system model under test (default: GEMINI_MODEL)")
    ap.add_argument("--recall-model", default=None, help="model for the recall grader (default: --model)")
    ap.add_argument("--summary-ids", default=None, help="comma-separated cached doc ids to use")
    ap.add_argument("--no-card-judge", action="store_true", help="skip LLM judging of recall cards (saves quota)")
    ap.add_argument("--from-results", default=None,
                    help="build the report/gates from existing JSONs (comma-separated paths) instead of re-running")
    ap.add_argument("--users", type=int, default=80)
    ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args()
    parts = set(a.only.split(","))
    out_dir = run_dir()
    results = {}
    if a.from_results:
        for path in a.from_results.split(","):
            name = Path(path).stem  # extraction | summary | recall | ranking
            results[name] = json.loads(Path(path).read_text())
        if "ranking" in results:  # JSON turns the int day keys into strings
            for row in results["ranking"]["results"].values():
                for key in ("ndcg@3", "ci95"):
                    row[key] = {int(d): v for d, v in row[key].items()}
            sweep = results["ranking"].get("k_sweep_mean_ndcg")
            if sweep:
                results["ranking"]["k_sweep_mean_ndcg"] = {int(kk): v for kk, v in sweep.items()}
        parts = set()
    if "extraction" in parts:
        print("\n== extraction ==")
        results["extraction"] = extraction_eval.run(out_dir)
    if "summary" in parts:
        print("\n== summary ==")
        results["summary"] = summary_eval.run(out_dir, limit=a.summary_limit, model=a.model,
                                              ids=a.summary_ids.split(",") if a.summary_ids else None,
                                              card_judge=not a.no_card_judge)
    if "recall" in parts:
        print("\n== recall grader ==")
        results["recall"] = recall_eval.run(out_dir, model=a.recall_model or a.model)
    if "ranking" in parts:
        print("\n== ranking ==")
        results["ranking"] = ranking_eval.run(out_dir, n_users=a.users, seeds=a.seeds)

    gate_results = {}
    for name, check in GATES.items():
        try:
            gate_results[name] = bool(check(results))
        except (KeyError, TypeError):
            gate_results[name] = None  # that eval wasn't run
    write_json(out_dir / "gates.json", gate_results)
    write_report(results, gate_results, out_dir)
    print(f"\nReport: {ROOT / 'REPORT.md'}")
    failed = [g for g, ok in gate_results.items() if ok is False]
    for g in failed:
        print(f"GATE FAILED: {g}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
