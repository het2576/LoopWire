"""Ranking eval: closed-loop simulated users, real embeddings.

Why simulation: offline ranking evals on logged data are biased by whatever
ranker produced the logs, and there is no real usage log yet. A simulator
with *known* ground-truth preferences lets every algorithm be scored against
the truth, with each algorithm generating its own training signal (rankings
change which items get clicked - a feedback loop).

User model (per synthetic user):
  - 12 topics: 2 loved (rel 3), 2 liked (2), 3 disliked (0), rest neutral (1)
  - written profile (70% of users) names ONE loved topic plus a decoy topic
    they don't actually care about - stated vs. revealed preference differ
  - opens each day's email with probability p_open ~ U(0.5, 0.95)
  - clicks item at position k with P = base[rel] * 1/(1 + 0.25k)  (position bias)
  - upvotes ~25% of loved clicks; downvotes ~10% of seen disliked items

Algorithms see only what that version of Loopwire would actually log:
  v1  per-item "opened" for EVERY item whenever the email is opened (pixel
      bug), clicks x2, skips -0.5 for items in older unopened sends, hard
      switch to the vector at 15 raw events, profile embedding before that
  v2  clicks, up/down votes, exposure-aware skips, recency decay, smooth
      profile/history blend with constant K, optional exploration slot

Metric: NDCG@3 on a held-out set of 8 fresh items per checkpoint day, graded
by true relevance. Common random numbers across algorithms: same candidates,
same coin flips - differences are due to the algorithm, not luck.

    uv run python -m evals.ranking_eval [--users 80 --seeds 3]
"""

import argparse
import datetime as dt
import json
from dataclasses import dataclass, field
from statistics import mean, stdev

import numpy as np

from app.embeddings import compute_embedding
from app.personalization import RankingContext, rank_items, weighted_interest_vector
from evals.common import cache_path, load_jsonl, run_dir, write_json

DAYS = 30
DISPATCH_SIZE = 6
HELDOUT_SIZE = 8
CHECKPOINTS = [1, 3, 7, 14, 30]
BASE_CLICK = {3: 0.6, 2: 0.35, 1: 0.12, 0: 0.03}
T0 = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

V1_WEIGHTS = {"opened": 1.0, "clicked_source": 2.0, "skipped": -0.5}
V1_THRESHOLD = 15


def pos_bias(k: int) -> float:
    return 1.0 / (1.0 + 0.25 * k)


def ndcg_at(ranked_rels: list[int], k: int = 3) -> float:
    def dcg(rels):
        return sum((2**r - 1) / np.log2(i + 2) for i, r in enumerate(rels[:k]))

    ideal = dcg(sorted(ranked_rels, reverse=True))
    return dcg(ranked_rels) / ideal if ideal > 0 else 1.0


def embed_cached(text: str) -> np.ndarray:
    p = cache_path("embeddings", text)
    if p.exists():
        return np.asarray(json.loads(p.read_text()))
    v = compute_embedding(text)
    p.write_text(json.dumps(v))
    return np.asarray(v)


def unit(v):
    n = np.linalg.norm(v)
    return v / n if n else v


@dataclass
class SimUser:
    uid: int
    rel: dict[str, int]
    profile_text: str | None
    p_open: float


def make_users(n: int, topics: list[str], desc: dict[str, str], rng: np.random.Generator) -> list[SimUser]:
    users = []
    for uid in range(n):
        perm = list(rng.permutation(topics))
        rel = {t: 1 for t in topics}
        for t in perm[:2]:
            rel[t] = 3
        for t in perm[2:4]:
            rel[t] = 2
        for t in perm[4:7]:
            rel[t] = 0
        profile = None
        if rng.random() < 0.7:
            decoy = perm[7 + int(rng.integers(0, len(perm) - 7))]
            profile = f"I'm interested in {desc[perm[0]]} and {desc[decoy]}."
        users.append(SimUser(uid, rel, profile, float(rng.uniform(0.5, 0.95))))
    return users


class _Obj:
    """Minimal stand-in for SavedItem accepted by app.personalization.rank_items."""

    def __init__(self, idx, emb):
        self.id, self.embedding, self.status = idx, emb, "summarized"


# ── algorithms ────────────────────────────────────────────────────────────────

@dataclass
class Algo:
    name: str
    emb: np.ndarray
    profile_vec: np.ndarray | None
    rng: np.random.Generator
    log: list = field(default_factory=list)  # dispatches: (day, [idx], opened, clicks:set, ups:set, downs:set)

    def rank(self, idxs: list[int], day: int, explore: bool = True) -> list[int]:
        raise NotImplementedError

    def observe(self, day, shown, opened, clicks, ups, downs):
        self.log.append((day, shown, opened, clicks, ups, downs))

    def adaptive(self) -> bool:
        return False


class RandomAlgo(Algo):
    def rank(self, idxs, day, explore=True):
        return list(self.rng.permutation(idxs))


class ProfileOnly(Algo):
    def rank(self, idxs, day, explore=True):
        if self.profile_vec is None:
            return list(self.rng.permutation(idxs))
        return sorted(idxs, key=lambda i: -float(self.emb[i] @ self.profile_vec))


class V1(Algo):
    def _events(self, day):
        ev = []
        for i, (_day, shown, opened, clicks, _, _) in enumerate(self.log):
            for pos, idx in enumerate(shown):
                if opened:
                    ev.append((idx, "opened"))  # one pixel per item -> every item "opened"
                if pos in clicks:
                    ev.append((idx, "clicked_source"))
                # v1 inferred skips for items in sends older than the latest
                # that had no opened/clicked event (i.e. unopened emails)
                if not opened and pos not in clicks and i < len(self.log) - 1:
                    ev.append((idx, "skipped"))
        return ev

    def vector(self):
        ev = self._events(None)
        if len(ev) < V1_THRESHOLD:
            return None
        acc, tot = np.zeros(self.emb.shape[1]), 0.0
        for idx, kind in ev:
            w = V1_WEIGHTS[kind]
            acc += self.emb[idx] * w
            tot += abs(w)
        return acc / tot

    def adaptive(self):
        return len(self._events(None)) >= V1_THRESHOLD

    def rank(self, idxs, day, explore=True):
        v = self.vector()
        if v is None:
            v = self.profile_vec
        if v is None:
            return list(self.rng.permutation(idxs))
        return sorted(idxs, key=lambda i: -float(self.emb[i] @ unit(v)))


class V2(Algo):
    def __init__(self, *a, k: float = 5, explore: bool = True, **kw):
        super().__init__(*a, **kw)
        self.k, self.explore = k, explore

    def _signals(self):
        sig, n_pos = [], set()
        for i, (d, shown, opened, clicks, ups, downs) in enumerate(self.log):
            ts = T0 + dt.timedelta(days=d)
            for pos, idx in enumerate(shown):
                key = (i, pos)
                if pos in ups:
                    sig.append((self.emb[idx].tolist(), "feedback_up", ts))
                    n_pos.add(key)
                if pos in downs:
                    sig.append((self.emb[idx].tolist(), "feedback_down", ts))
                if pos in clicks:
                    sig.append((self.emb[idx].tolist(), "clicked_source", ts))
                    n_pos.add(key)
                elif opened and pos not in downs and i < len(self.log) - 1:
                    sig.append((self.emb[idx].tolist(), "skipped", ts))
        return sig, len(n_pos)

    def ctx(self, day) -> RankingContext:
        sig, n = self._signals()
        vec = weighted_interest_vector(sig, T0 + dt.timedelta(days=day)) if n else None
        alpha = n / (n + self.k) if vec is not None else 0.0
        return RankingContext(vec, self.profile_vec.tolist() if self.profile_vec is not None else None, alpha, n)

    def adaptive(self):
        sig, n = self._signals()
        return n >= self.k

    def rank(self, idxs, day, explore=True):
        c = self.ctx(day)
        if not c.has_signal:
            return list(self.rng.permutation(idxs))
        ranked = rank_items([_Obj(i, self.emb[i].tolist()) for i in idxs], c, explore=explore and self.explore)
        return [r.item.id for r in ranked]


# ── simulation ────────────────────────────────────────────────────────────────

def simulate(algo_factory, user: SimUser, topics_of: list[str], n_items: int, seed: int) -> dict:
    crn = np.random.default_rng([seed, user.uid])
    algo = algo_factory(np.random.default_rng([seed, user.uid, 7]))
    scores, adaptive_day = {}, None
    rel_of = [user.rel[t] for t in topics_of]
    for day in range(1, DAYS + 1):
        cand = list(crn.choice(n_items, DISPATCH_SIZE, replace=False))
        u_open, u_click, u_fb = crn.random(), crn.random(n_items), crn.random(n_items)
        held = list(crn.choice(n_items, HELDOUT_SIZE, replace=False))
        if day in CHECKPOINTS:
            ranked = algo.rank(held, day, explore=False)
            scores[day] = ndcg_at([rel_of[i] for i in ranked])
        shown = algo.rank(cand, day)
        opened = u_open < user.p_open
        clicks, ups, downs = set(), set(), set()
        if opened:
            for pos, idx in enumerate(shown):
                r = rel_of[idx]
                if u_click[idx] < BASE_CLICK[r] * pos_bias(pos):
                    clicks.add(pos)
                    if r == 3 and u_fb[idx] < 0.25:
                        ups.add(pos)
                elif r == 0 and u_fb[idx] < 0.10:
                    downs.add(pos)
        algo.observe(day, shown, opened, clicks, ups, downs)
        if adaptive_day is None and algo.adaptive():
            adaptive_day = day
    return {"ndcg": scores, "adaptive_day": adaptive_day}


def ci95(xs):
    return round(1.96 * stdev(xs) / np.sqrt(len(xs)), 4) if len(xs) > 1 else 0.0


def run(out_dir=None, n_users: int = 80, seeds: int = 3) -> dict:
    out_dir = out_dir or run_dir()
    corpus = load_jsonl("ranking_corpus.jsonl")
    topics = sorted({c["topic"] for c in corpus})
    desc = {c["topic"]: c["topic_desc"] for c in corpus}
    emb = np.stack([unit(embed_cached(c["summary"])) for c in corpus])
    topics_of = [c["topic"] for c in corpus]

    # Embedding sanity: same-topic items should be closer than cross-topic.
    sims = emb @ emb.T
    same = [sims[i, j] for i in range(len(corpus)) for j in range(len(corpus)) if i < j and topics_of[i] == topics_of[j]]
    diff = [sims[i, j] for i in range(len(corpus)) for j in range(len(corpus)) if i < j and topics_of[i] != topics_of[j]]

    variants = {
        "random": lambda pv: (lambda r: RandomAlgo("random", emb, pv, r)),
        "profile_only": lambda pv: (lambda r: ProfileOnly("profile_only", emb, pv, r)),
        "v1": lambda pv: (lambda r: V1("v1", emb, pv, r)),
        "v2_k3_explore": lambda pv: (lambda r: V2("v2", emb, pv, r, k=3, explore=True)),
        "v2_k3_no_explore": lambda pv: (lambda r: V2("v2", emb, pv, r, k=3, explore=False)),
    }
    for k in (1, 2, 5, 8, 13):
        variants[f"v2_k{k}_explore"] = (lambda kk: lambda pv: (lambda r: V2("v2", emb, pv, r, k=kk, explore=True)))(k)

    results: dict[str, dict] = {}
    for name, factory in variants.items():
        per_day = {d: [] for d in CHECKPOINTS}
        adaptive_days = []
        for seed in range(seeds):
            users = make_users(n_users, topics, desc, np.random.default_rng(1000 + seed))
            for u in users:
                pv = unit(embed_cached(u.profile_text)) if u.profile_text else None
                out = simulate(factory(pv), u, topics_of, len(corpus), seed)
                for d, s in out["ndcg"].items():
                    per_day[d].append(s)
                adaptive_days.append(out["adaptive_day"])
        reached = [d for d in adaptive_days if d is not None]
        results[name] = {
            "ndcg@3": {d: round(float(mean(v)), 4) for d, v in per_day.items()},
            "ci95": {d: ci95(v) for d, v in per_day.items()},
            "ndcg@3_mean_all_days": round(float(mean(x for v in per_day.values() for x in v)), 4),
            "claims_adaptive_by_day": round(mean(reached), 1) if reached else None,
            "share_reaching_adaptive": round(len(reached) / len(adaptive_days), 3),
        }
        r = results[name]
        print(f"  {name:<18} " + "  ".join(f"d{d}={r['ndcg@3'][d]:.3f}" for d in CHECKPOINTS)
              + f"  mean={r['ndcg@3_mean_all_days']:.3f}  adaptive@day={r['claims_adaptive_by_day']}")

    sweep = {k: float(results[f"v2_k{k}_explore"]["ndcg@3_mean_all_days"]) for k in (1, 2, 3, 5, 8, 13)}
    out = {
        "users": n_users, "seeds": seeds, "days": DAYS,
        "embedding_sanity": {"same_topic_cos": round(float(np.mean(same)), 3),
                             "cross_topic_cos": round(float(np.mean(diff)), 3)},
        "results": results,
        "k_sweep_mean_ndcg": sweep,
        "best_k": max(sweep, key=sweep.get),
    }
    write_json(out_dir / "ranking.json", out)
    print(f"  embedding sanity: {out['embedding_sanity']}  best K={out['best_k']} sweep={sweep}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=80)
    ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args()
    run(n_users=a.users, seeds=a.seeds)
