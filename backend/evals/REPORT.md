# Loopwire eval report

Run: `20261116-010320`

## Gates

| Gate | Result |
|---|---|
| `extraction.fully_correct_rate >= 0.90` | ✅ pass |
| `summary.v2.faithfulness_mean >= 0.90` | ✅ pass |
| `summary.v2.injection_canary_leaked == 0` | ✅ pass |
| `summary.v2.english_output == 1` | ✅ pass |
| `summary.v2.card_grounding_rate >= 0.85` | ✅ pass |
| `recall.accuracy >= 0.80 (all cases graded)` | ✅ pass |
| `recall.false_accept_rate <= 0.10` | ✅ pass |
| `ranking.v2 beats v1 at day 14` | ✅ pass |

## Extraction

25 live URLs. Fully correct (right outcome **and** right failure reason): **100%**. By type: article 16/16, github 2/2, hn 1/1, pdf 1/1, youtube 5/5.

## Summarization (v1 prompt vs v2 prompt)

System model: `gemini-3.5-flash-lite` · judge: `gemini-4-hydrogen`. A/B columns are **paired** on the 5 documents where both versions completed; the last column is v2 on all 15 completed documents (real extractions + adversarial); 3 v2 row(s) incomplete.

| Metric | v1 (paired) | v2 (paired) | v2 (all) |
|---|---|---|---|
| Claim-level faithfulness (↑) | 0.849 | 0.945 | 0.976 |
| Docs with ≥1 unsupported claim (↓) | 0.600 | 0.400 | 0.200 |
| Main-point coverage 1–5 (↑) | 4.200 | 4.200 | 4.667 |
| Long doc: conclusion at the end captured (↑) | – | – | – |
| Paywall teaser flagged as thin (↑) | – | – | 1 |
| Prompt-injection canary leaked (↓) | 0 | 0 | 0 |
| English output (↑) | 1 | 1 | 1 |
| ≤3 sentences (↑) | 1 | 1 | 1 |
| No 'The article discusses…' opener (↑) | 0.800 | 1 | 0.933 |
| Read-time error vs. word count (↓) | 0.406 | 0.000 | 0.000 |

Recall cards (v2): 30 generated, grounding rate 1.000, answerable 1, tests a key idea 0.857, open-ended 0.929.

## Recall grader

Grader model `gemini-3.5-flash-lite`. 28/28 hand-labeled answers graded. Accuracy **96%**, false-accept rate **0.000**, severe (correct↔incorrect) errors: 0, injection attempts resisted: 3/3.

By category: empty 1/1, exact 5/5, informal 2/2, injection 3/3, keyword_stuffing 1/1, paraphrase 3/3, partial 4/5, rambling 1/1, vague 1/1, wrong 6/6.

## Ranking (closed-loop simulation)

80 users × 3 seeds × 30 days. NDCG@3 on held-out items (1.0 = perfect order). Embedding sanity: same-topic cos 0.769 vs cross-topic 0.717.

| Algorithm | day 1 | day 3 | day 7 | day 14 | day 30 | claims adaptive by day |
|---|---|---|---|---|---|---|
| random | 0.480 | 0.453 | 0.419 | 0.455 | 0.437 | – |
| profile_only | 0.532 | 0.539 | 0.493 | 0.505 | 0.501 | – |
| v1 | 0.532 | 0.541 | 0.463 | 0.488 | 0.482 | 3.100 |
| v2_k3_no_explore | 0.532 | 0.571 | 0.607 | 0.682 | 0.727 | 5.700 |
| v2_k3_explore | 0.532 | 0.571 | 0.607 | 0.687 | 0.728 | 5.700 |

K sweep (mean NDCG@3): {'1': 0.6248, '2': 0.6275, '3': 0.6251, '5': 0.6194, '8': 0.6169, '13': 0.6106} → numerically best K = 2; K 1–5 differ by less than the ±0.035 95% CI, so production uses K = 3 (most conservative value within noise of the best).

## LLM usage

| op@model | calls | failed attempts | input tok | output tok | p50 ms | p95 ms |
|---|---|---|---|---|---|---|
| judge_cards@gemini-4-hydrogen | 2 | 1 | 1,757 | 106 | 9888 | 9888 |
| judge_faithfulness@gemini-4-hydrogen | 3 | 16 | 11,952 | 732 | 12032 | 13850 |
