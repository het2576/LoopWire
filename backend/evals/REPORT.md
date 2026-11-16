# Loopwire eval report

Run: `20261116-115832`

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

System model: `gemini-3.5-flash-lite` · judge: `gemini-4-hydrogen`. A/B columns are **paired** on the 8 documents where both versions completed; the last column is v2 on all 18 completed documents (real extractions + adversarial).

| Metric | v1 (paired) | v2 (paired) | v2 (all) |
|---|---|---|---|
| Claim-level faithfulness (↑) | 0.839 | 0.966 | 0.973 |
| Docs with ≥1 unsupported claim (↓) | 0.625 | 0.250 | 0.222 |
| Main-point coverage 1–5 (↑) | 4.375 | 4.500 | 4.722 |
| Long doc: conclusion at the end captured (↑) | – | – | 1 |
| Paywall teaser flagged as thin (↑) | – | – | 1 |
| Prompt-injection canary leaked (↓) | 0 | 0 | 0 |
| English output (↑) | 1 | 1 | 1 |
| ≤3 sentences (↑) | 1 | 1 | 1 |
| No 'The article discusses…' opener (↑) | 0.875 | 1 | 0.944 |
| Read-time error vs. word count (↓) | 0.395 | 0.000 | 0.000 |

Recall cards (v2): 32 generated, grounding rate 1.000, answerable 1, tests a key idea 0.844, open-ended 0.938.

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

K sweep (mean NDCG@3): {1: 0.6248, 2: 0.6275, 3: 0.6251, 5: 0.6194, 8: 0.6169, 13: 0.6106} → numerically best K = 2; K 1–5 differ by less than the ±0.035 95% CI, so production uses K = 3 (most conservative value within noise of the best).

## LLM usage

| op@model | calls | failed attempts | input tok | output tok | p50 ms | p95 ms |
|---|---|---|---|---|---|---|
| judge_cards@gemini-4-hydrogen | 4 | 1 | 32,925 | 212 | 9888 | 10740 |
| judge_faithfulness@gemini-4-hydrogen | 4 | 26 | 19,458 | 1,165 | 13850 | 27351 |
