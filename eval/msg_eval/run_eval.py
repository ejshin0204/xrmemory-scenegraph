"""Run retrieval methods over the in-graph gold set and score nDCG@k.

From the repo root:
  cd eval && uv run python -m msg_eval.run_eval --config config.yaml --methods bm25,llm_flat,graph_nav
  cd eval && uv run python -m msg_eval.run_eval --config config.yaml --methods graph_nav --limit 5

Writes eval/runs/<timestamp>_<methods>/:
  run_meta.json            config (no key), model, graph/dataset hashes, git commit, counts
  run.log                  console log
  traces/<method>/<qid>.json  every LLM turn (summarized thinking, text, tool calls), tool outputs, usage
  results_<method>.csv     per question: ranking, gold, metrics, answer, steps, errors
  summary.json / summary.md  means overall and by qtype / origin / step-or-button
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import subprocess
import sys
import time
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import yaml

from . import agents, dataset, metrics
from .graph import MemorySceneGraph

REPO = Path(__file__).resolve().parents[2]
log = logging.getLogger("msg_eval")


def _path(p: str) -> Path:
    q = Path(p).expanduser()
    return q if q.is_absolute() else REPO / q


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return None


def _setup_logging(run_dir: Path, verbose: bool) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    log.setLevel(logging.DEBUG)
    fh = logging.FileHandler(run_dir / "run.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.DEBUG if verbose else logging.INFO)
    sh.setFormatter(fmt)
    log.handlers[:] = [fh, sh]


def _mean(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 4) if xs else 0.0


def summarize(rows: list[dict[str, Any]], k: int) -> dict[str, Any]:
    keys = [f"ndcg@{k}", f"recall@{k}", f"recall_any@{k}", f"hit@{k}", "hit@1", "mrr"]
    out: dict[str, Any] = {"n": len(rows), "n_errors": sum(1 for r in rows if r["error"]),
                           "overall": {m: _mean([r[m] for r in rows]) for m in keys}}
    for field in ("qtype", "origin", "facet", "scenario_step"):
        groups: dict[str, list] = defaultdict(list)
        for r in rows:
            groups[r[field] or "-"].append(r)
        out[f"by_{field}"] = {g: {"n": len(v), **{m: _mean([r[m] for r in v]) for m in keys}}
                              for g, v in sorted(groups.items())}
    usage = defaultdict(int)
    for r in rows:
        for kk, vv in (r.get("_usage") or {}).items():
            usage[kk] += vv or 0
    out["usage_total"] = dict(usage)  # logged only; not an evaluation metric
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--methods", default="bm25,llm_flat,graph_nav")
    ap.add_argument("--dataset", help="override config dataset path")
    ap.add_argument("--limit", type=int, help="first N questions only (smoke test)")
    ap.add_argument("--qids", help="comma-separated qids to run")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = (Path.cwd() / cfg_path) if (Path.cwd() / cfg_path).exists() else REPO / "eval" / cfg_path
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    k = int(cfg.get("evaluation", {}).get("k", 5))
    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    for m in methods:
        if m not in agents.METHODS:
            raise SystemExit(f"unknown method {m}; choose from {list(agents.METHODS)}")

    graph_path = _path(cfg["graph"])
    data_path = _path(args.dataset or cfg["dataset"])
    msg = MemorySceneGraph(graph_path)
    items = dataset.load(data_path, valid_ids=set(msg.nodes))
    if args.qids:
        want = {q.strip() for q in args.qids.split(",")}
        items = [it for it in items if it.qid in want]
    if args.limit:
        items = items[: args.limit]

    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = _path(cfg.get("runs_dir", "eval/runs")) / f"{stamp}_{'+'.join(methods)}"
    run_dir.mkdir(parents=True, exist_ok=True)
    _setup_logging(run_dir, args.verbose)

    client = None
    if any(m in agents.LLM_METHODS for m in methods):
        from . import llm
        client = llm.make_client(cfg)

    safe_cfg = json.loads(json.dumps(cfg))
    meta = {"started": stamp, "methods": methods, "k": k, "n_questions": len(items),
            "graph": str(graph_path.relative_to(REPO)), "graph_sha": dataset.file_sha(graph_path),
            "dataset": str(data_path.relative_to(REPO)) if data_path.is_relative_to(REPO) else str(data_path),
            "dataset_sha": dataset.file_sha(data_path), "git_commit": _git_commit(), "config": safe_cfg,
            "references": {
                "navigation": "Graph-CoT, Jin et al., Findings of ACL 2024 (2024.findings-acl.11)",
                "task_framing": "TSG Bench, Yang et al., ACL 2025 (2025.acl-long.1036)",
                "metric": "nDCG@k, Jarvelin & Kekalainen 2002; gain 2^rel-1"}}
    (run_dir / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("run %s | %d questions | methods %s | model %s", run_dir.name, len(items), methods,
             cfg.get("anthropic", {}).get("model"))

    all_summary: dict[str, Any] = {}
    for method in methods:
        fn = agents.METHODS[method]
        tdir = run_dir / "traces" / method
        tdir.mkdir(parents=True, exist_ok=True)
        jobs = int(cfg.get("evaluation", {}).get("parallel_jobs", 4)) if method in agents.LLM_METHODS else 1

        def one(it: dataset.QAItem) -> dict[str, Any]:
            t0, err, res = time.time(), "", None
            try:
                res = fn(client, cfg, msg, it.question, k)
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
                log.error("%s %s failed: %s", method, it.qid, err)
                log.debug(traceback.format_exc())
            ranked = res.ranked if res else []
            sc = metrics.score(ranked, it.gold_2, it.gold_1, k)
            usage = defaultdict(int)
            for t in (res.trace if res else []):
                for kk, vv in (t.get("usage") or {}).items():
                    usage[kk] += vv or 0
            trace = {"qid": it.qid, "question": it.question, "gold_2": it.gold_2, "gold_1": it.gold_1,
                     "ranked": ranked, "answer": res.answer if res else "", "scores": sc, "error": err,
                     "steps": res.steps if res else 0, "forced_stop": res.forced_stop if res else False,
                     "padded": res.padded if res else 0, "seconds": round(time.time() - t0, 2),
                     "trace": res.trace if res else []}
            (tdir / f"{it.qid}.json").write_text(json.dumps(trace, ensure_ascii=False, indent=1, default=str),
                                                 encoding="utf-8")
            log.info("%-9s %s ndcg@%d=%.3f hit@%d=%d steps=%d%s%s", method, it.qid, k, sc[f"ndcg@{k}"], k,
                     sc[f"hit@{k}"], trace["steps"], " FORCED" if trace["forced_stop"] else "",
                     f" ERROR {err}" if err else "")
            return {"qid": it.qid, "qtype": it.qtype, "origin": it.origin,
                    "facet": it.step or it.button, "scenario_ref": it.scenario_ref,
                    "scenario_step": it.scenario_step or "(episodic)", "question": it.question,
                    "ranked": ";".join(ranked), "gold_2": ";".join(it.gold_2), "gold_1": ";".join(it.gold_1),
                    **{m: round(v, 4) for m, v in sc.items()},
                    "answer": trace["answer"], "steps": trace["steps"], "forced_stop": trace["forced_stop"],
                    "padded": trace["padded"], "seconds": trace["seconds"], "error": err, "_usage": dict(usage)}

        rows: list[dict[str, Any]] = []
        todo = list(items)
        if method in agents.LLM_METHODS and todo:
            # Warm the prompt cache with one question before going parallel; requests sent at the
            # same moment cannot read a cache entry none of them has written yet.
            rows.append(one(todo.pop(0)))
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
            futs = [ex.submit(one, it) for it in todo]
            for f in as_completed(futs):
                rows.append(f.result())
        order = {it.qid: i for i, it in enumerate(items)}
        rows.sort(key=lambda r: order[r["qid"]])
        cols = [c for c in rows[0] if not c.startswith("_")] if rows else []
        with open(run_dir / f"results_{method}.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        all_summary[method] = summarize(rows, k)
        o = all_summary[method]["overall"]
        log.info("== %s: nDCG@%d %.4f | Recall@%d %.4f | Hit@%d %.4f | MRR %.4f | errors %d", method, k,
                 o[f"ndcg@{k}"], k, o[f"recall@{k}"], k, o[f"hit@{k}"], o["mrr"], all_summary[method]["n_errors"])

    (run_dir / "summary.json").write_text(json.dumps(all_summary, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(run_dir / "summary.md", "w", encoding="utf-8") as f:
        f.write(f"# {run_dir.name}\n\nN = {len(items)} questions, k = {k}, model = "
                f"{cfg.get('anthropic', {}).get('model')}\n\n")
        f.write(f"| method | nDCG@{k} | Recall@{k} | RecallAny@{k} | Hit@{k} | Hit@1 | MRR | errors |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        for m, s in all_summary.items():
            o = s["overall"]
            f.write(f"| {m} | {o[f'ndcg@{k}']:.4f} | {o[f'recall@{k}']:.4f} | {o[f'recall_any@{k}']:.4f} | "
                    f"{o[f'hit@{k}']:.4f} | {o['hit@1']:.4f} | {o['mrr']:.4f} | {s['n_errors']} |\n")
        for m, s in all_summary.items():
            f.write(f"\n## {m} by qtype\n\n| qtype | n | nDCG@{k} | Hit@{k} |\n|---|---|---|---|\n")
            for g, v in s["by_qtype"].items():
                f.write(f"| {g} | {v['n']} | {v[f'ndcg@{k}']:.4f} | {v[f'hit@{k}']:.4f} |\n")
            f.write(f"\n## {m} by scenario step\n\n| step | n | nDCG@{k} | Hit@{k} |\n|---|---|---|---|\n")
            for g, v in s["by_scenario_step"].items():
                f.write(f"| {g} | {v['n']} | {v[f'ndcg@{k}']:.4f} | {v[f'hit@{k}']:.4f} |\n")
    log.info("done -> %s", run_dir)


if __name__ == "__main__":
    main()
