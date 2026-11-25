"""Ranking metrics with graded relevance (gold_2 -> rel 2, gold_1 -> rel 1, else 0).

nDCG@k follows Järvelin & Kekäläinen (2002) with the exponential gain 2^rel - 1 (Burges et al., 2005),
the form used by BEIR and TREC tooling. IDCG@k is computed from the gold grades, so a question whose
gold holds fewer than k nodes can still reach 1.0.
"""
from __future__ import annotations

import math


def dedupe(ranked: list[str]) -> list[str]:
    seen, out = set(), []
    for r in ranked:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def dcg(rels: list[int], k: int) -> float:
    return sum((2 ** r - 1) / math.log2(i + 2) for i, r in enumerate(rels[:k]))


def ndcg_at_k(ranked: list[str], grades: dict[str, int], k: int = 5) -> float:
    ranked = dedupe(ranked)
    ideal = dcg(sorted(grades.values(), reverse=True), k)
    if ideal == 0:
        return 0.0
    return dcg([grades.get(r, 0) for r in ranked], k) / ideal


def recall_at_k(ranked: list[str], targets: set[str], k: int = 5) -> float:
    if not targets:
        return 0.0
    return len(set(dedupe(ranked)[:k]) & targets) / len(targets)


def hit_at_k(ranked: list[str], targets: set[str], k: int = 5) -> float:
    return float(bool(set(dedupe(ranked)[:k]) & targets))


def mrr(ranked: list[str], targets: set[str]) -> float:
    for i, r in enumerate(dedupe(ranked)):
        if r in targets:
            return 1.0 / (i + 1)
    return 0.0


def score(ranked: list[str], gold_2: list[str], gold_1: list[str], k: int = 5) -> dict[str, float]:
    grades = {g: 1 for g in gold_1}
    grades.update({g: 2 for g in gold_2})
    answer = set(gold_2)
    return {
        f"ndcg@{k}": ndcg_at_k(ranked, grades, k),
        f"recall@{k}": recall_at_k(ranked, answer, k),       # over relevance-2 (answer) nodes
        f"recall_any@{k}": recall_at_k(ranked, set(grades), k),
        f"hit@{k}": hit_at_k(ranked, answer, k),
        "hit@1": hit_at_k(ranked, answer, 1),
        "mrr": mrr(ranked, answer),
    }


if __name__ == "__main__":  # sanity checks
    g2, g1 = ["a"], ["b", "c"]
    assert score(["a", "b", "c"], g2, g1)["ndcg@5"] == 1.0
    assert score(["x", "y", "z", "w", "v"], g2, g1)["ndcg@5"] == 0.0
    s = score(["b", "a"], g2, g1)
    assert 0 < s["ndcg@5"] < 1 and s["hit@5"] == 1 and s["mrr"] == 0.5
    assert score(["a", "a", "a"], g2, [])["ndcg@5"] == 1.0  # duplicates count once
    print("metrics ok", s)
