"""Retrieval methods that return a ranked list of node ids for a question.

graph_nav (ours)  Navigator agent + Ranker agent.
                  The Navigator adapts Graph-CoT (Jin et al., Findings of ACL 2024): each turn the LLM
                  reasons, calls a graph function, and reads the result, until it calls `finish` with
                  candidate nodes. Graph-CoT's RetrieveNode / NodeFeature / NeighborCheck map to
                  search_nodes / get_node / get_neighbors (RetrieveNode is embedding search there; here
                  it is BM25; NodeDegree is not used); get_time_window and get_decision_point are
                  added for the episodic (time-indexed) part of a memory scene graph. Graph-CoT outputs
                  an answer; here a separate Ranker reads the candidates' full features and returns
                  the top-k node ids, which nDCG@k scores.
llm_flat          Baseline: the whole candidate-node table serialized into the prompt, as TSG Bench
                  (Yang et al., ACL 2025) gives scene graphs to the LLM as text; one call returns the
                  top-k. TSG Bench's SGQA answers with a single graph element (exact match); this
                  benchmark asks for a ranked top-k of graph nodes instead.
bm25              Baseline: lexical BM25 over node text, no LLM.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from . import llm
from .graph import CANDIDATE_TYPES, MemorySceneGraph

log = logging.getLogger("msg_eval")


@dataclass
class Retrieval:
    ranked: list[str]
    answer: str = ""
    steps: int = 0
    forced_stop: bool = False
    padded: int = 0                       # ids added by BM25 because the method returned fewer than k
    trace: list[dict] = field(default_factory=list)


def _j(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def _pad(ranked: list[str], msg: MemorySceneGraph, question: str, k: int) -> tuple[list[str], int]:
    out = []
    for r in ranked:
        if r in msg.nodes and r not in out:
            out.append(r)
    n0 = len(out)
    if len(out) < k:
        for h in msg.search(question, k=len(msg.nodes)):
            if h["id"] not in out:
                out.append(h["id"])
            if len(out) >= k:
                break
    return out[:k], len(out[:k]) - min(n0, k)


def _schema_text(msg: MemorySceneGraph) -> str:
    return (
        "The memory scene graph (MSG) was extracted from one recorded trial: an expert operator performs the "
        "normal procedure at a CNC oxy-fuel cutting machine control panel (STARFIRE keypad with a small LCD that "
        "shows the last pressed key; the cutting machine is projected on the front wall) while thinking aloud.\n"
        "Node types:\n"
        "- object: control panel, screen, key groups, control zones, buttons (BTN_*), projected machine\n"
        "- state: what the LCD showed over a time span, with the task state (S0-S4) and the spoken phase\n"
        "- event: button presses (time, physical key, key group, observed LCD change), looks up at the projected "
        "machine, an initial key exploration\n"
        "- observation: what the operator reported seeing or checking (think-aloud)\n"
        "- interpretation: the operator's judgments, intentions to press a button, and plans (monitoring cues, "
        "planned responses to anomalies, actions held back)\n"
        "- decision_point: DP1-DP5, consecutive time windows of the procedure\n"
        "Times are seconds from trial start.\n"
        f"Graph overview: {_j(msg.overview())}"
    )


# --------------------------------------------------------------------- tools
def tool_defs(msg: MemorySceneGraph) -> list[dict]:
    rels = sorted({e.relation for e in msg.edges})
    dps = [n.id for n in msg.nodes.values() if n.type == "decision_point"]
    types = {"type": "array", "items": {"type": "string", "enum": list(CANDIDATE_TYPES)},
             "description": "Restrict to these node types; empty list = all types."}

    def obj(props: dict, desc: str, name: str) -> dict:
        return {"name": name, "description": desc, "strict": True,
                "input_schema": {"type": "object", "properties": props, "required": list(props),
                                 "additionalProperties": False}}

    return [
        obj({"query": {"type": "string", "description": "Keywords or a short phrase (Korean or English)."},
             "types": types},
            "Lexical search over node text. Returns up to 10 nodes with id, type, time, decision point and "
            "text, best match first.", "search_nodes"),
        obj({"node_id": {"type": "string"}},
            "All stored attributes of one node.", "get_node"),
        obj({"node_id": {"type": "string"},
             "relation": {"type": "string", "enum": [""] + rels, "description": "One relation, or '' for all."}},
            "Nodes linked to node_id in either direction, with the relation name and direction.", "get_neighbors"),
        obj({"start_s": {"type": "number"}, "end_s": {"type": "number"}, "types": types},
            "Nodes whose time span overlaps [start_s, end_s] seconds, in time order.", "get_time_window"),
        obj({"dp_id": {"type": "string", "enum": dps}},
            "A decision point with its time window and all nodes inside it, in time order.", "get_decision_point"),
        obj({"candidates": {"type": "array", "items": {
                "type": "object", "properties": {"id": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["id", "reason"], "additionalProperties": False}},
             "notes": {"type": "string", "description": "One or two sentences on what you found."}},
            "End the search. Candidate node ids, most relevant first, each with a one-line reason.", "finish"),
    ]


def run_tool(msg: MemorySceneGraph, name: str, args: dict[str, Any]) -> Any:
    if name == "search_nodes":
        return msg.search(args["query"], k=10, types=args.get("types") or None)
    if name == "get_node":
        return msg.node_feature(args["node_id"])
    if name == "get_neighbors":
        return msg.neighbors(args["node_id"], args.get("relation") or None)
    if name == "get_time_window":
        return msg.time_window(float(args["start_s"]), float(args["end_s"]), args.get("types") or None)
    if name == "get_decision_point":
        return msg.decision_point(args["dp_id"])
    raise KeyError(f"unknown tool {name}")


# ----------------------------------------------------------------- graph_nav
NAV_TASK = (
    "You are the Navigator. A novice operator asks a question. Find the graph nodes that hold the answer: "
    "the node(s) whose content directly answers it, and the nodes a reader needs for context (the button, the "
    "press event, the LCD state, the decision point). Do not answer the question yourself.\n"
    "Explore with the tools: search, read nodes, follow neighbours, scan time windows or decision points. "
    "Questions use everyday on-site wording and the 7-step procedure names (S0 before start, S1 system "
    "activation, S2 conditions applied, S3 ignition, S4 preheating, S5 piercing, S6 automatic cutting), which "
    "do not match node text word for word; try synonyms and neighbouring steps when a search misses.\n"
    "When you have the evidence, call finish with up to {max_candidates} candidate ids, most relevant first. "
    "Use only ids that the tools returned."
)

RANK_TASK = (
    "You are the Ranker. Given a novice's question and candidate nodes from a memory scene graph, return the "
    "{k} node ids that best answer it, most relevant first: nodes whose content directly answers the question "
    "come first, then nodes that give needed context. Use only ids from the candidate list. Also write a short "
    "Korean answer grounded only in these nodes."
)


def _rank_schema() -> dict:
    return {"type": "json_schema", "schema": {
        "type": "object",
        "properties": {"ranking": {"type": "array", "items": {"type": "string"}},
                       "answer": {"type": "string"}},
        "required": ["ranking", "answer"], "additionalProperties": False}}


def graph_nav(client, cfg: dict, msg: MemorySceneGraph, question: str, k: int) -> Retrieval:
    mcfg = cfg["methods"]["graph_nav"]
    max_steps, max_cand = int(mcfg.get("max_steps", 12)), int(mcfg.get("max_candidates", 10))
    tools = tool_defs(msg)
    system = _schema_text(msg) + "\n\n" + NAV_TASK.format(max_candidates=max_cand)
    messages: list[dict] = [{"role": "user", "content": f"Question: {question}"}]
    trace: list[dict] = []
    seen: list[str] = []          # ids the tools returned, first-seen order (fallback if no finish)
    candidates: list[dict] = []
    notes, finished, steps, nudged = "", False, 0, False

    def note_ids(x: Any) -> None:
        if isinstance(x, dict):
            if isinstance(x.get("id"), str) and x["id"] in msg.nodes and x["id"] not in seen:
                seen.append(x["id"])
            for v in x.values():
                note_ids(v)
        elif isinstance(x, list):
            for v in x:
                note_ids(v)

    while steps < max_steps and not finished:
        steps += 1
        resp = llm.call(client, cfg, system=system, messages=messages, tools=tools, trace=trace, tag=f"nav{steps}")
        messages.append({"role": "assistant", "content": resp.content})
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            if nudged:
                break
            nudged = True
            messages.append({"role": "user", "content": "Call finish with your candidate node ids."})
            continue
        results = []
        for u in uses:
            if u.name == "finish":
                candidates = list(u.input.get("candidates") or [])
                notes = u.input.get("notes", "")
                finished = True
                out: Any = {"ok": True}
            else:
                try:
                    out = run_tool(msg, u.name, u.input)
                    note_ids(out)
                except Exception as e:  # report the error to the model, keep going
                    results.append({"type": "tool_result", "tool_use_id": u.id, "content": f"Error: {e}",
                                    "is_error": True})
                    trace.append({"tag": f"tool{steps}", "name": u.name, "input": u.input, "error": str(e)})
                    continue
            trace.append({"tag": f"tool{steps}", "name": u.name, "input": u.input, "output": out})
            results.append({"type": "tool_result", "tool_use_id": u.id, "content": _j(out)})
        messages.append({"role": "user", "content": results})

    forced = not finished
    cand_ids = [c["id"] for c in candidates if c.get("id") in msg.nodes]
    if forced or not cand_ids:
        cand_ids = cand_ids or seen
        candidates = candidates or [{"id": i, "reason": "seen during navigation (no finish)"} for i in cand_ids]
    cand_ids = list(dict.fromkeys(cand_ids))[:max_cand]
    if not cand_ids:
        ranked, pad = _pad([], msg, question, k)
        return Retrieval(ranked, "", steps, forced, pad, trace)

    # ---- Ranker
    reasons = {c["id"]: c.get("reason", "") for c in candidates}
    cand_view = [{"id": i, "navigator_reason": reasons.get(i, ""), **msg.node_feature(i)} for i in cand_ids]
    rank_system = _schema_text(msg) + "\n\n" + RANK_TASK.format(k=k)
    rank_user = (f"Question: {question}\n\nNavigator notes: {notes}\n\n"
                 f"Candidates (most relevant first, per the Navigator):\n{_j(cand_view)}")
    resp = llm.call(client, cfg, system=rank_system, messages=[{"role": "user", "content": rank_user}],
                    output_format=_rank_schema(), trace=trace, tag="rank")
    out = json.loads(llm.final_text(resp))
    ranked = [r for r in out.get("ranking", []) if r in cand_ids]
    ranked = list(dict.fromkeys(ranked + cand_ids))  # unranked candidates keep Navigator order behind
    ranked, pad = _pad(ranked, msg, question, k)
    return Retrieval(ranked, out.get("answer", ""), steps, forced, pad, trace)


# ------------------------------------------------------------------ llm_flat
FLAT_TASK = (
    "Below is every node of the graph. A novice operator asks a question. Return the {k} node ids that best "
    "answer it, most relevant first: nodes whose content directly answers the question come first, then nodes "
    "that give needed context (the button, the press event, the LCD state, the decision point). Use only ids "
    "from the table. Also write a short Korean answer grounded only in the graph."
)


def llm_flat(client, cfg: dict, msg: MemorySceneGraph, question: str, k: int) -> Retrieval:
    table = "\n".join(_j(msg.brief(n, width=10_000)) for n in msg.nodes.values())
    system = _schema_text(msg) + "\n\n" + FLAT_TASK.format(k=k) + "\n\nNodes (JSON lines):\n" + table
    trace: list[dict] = []
    resp = llm.call(client, cfg, system=system, messages=[{"role": "user", "content": f"Question: {question}"}],
                    output_format=_rank_schema(), trace=trace, tag="flat")
    out = json.loads(llm.final_text(resp))
    ranked, pad = _pad(out.get("ranking", []), msg, question, k)
    return Retrieval(ranked, out.get("answer", ""), 1, False, pad, trace)


# ---------------------------------------------------------------------- bm25
def bm25(client, cfg: dict, msg: MemorySceneGraph, question: str, k: int) -> Retrieval:
    hits = msg.search(question, k=k)
    ranked, pad = _pad([h["id"] for h in hits], msg, question, k)
    return Retrieval(ranked, "", 0, False, pad, [{"tag": "bm25", "hits": hits}])


METHODS = {"graph_nav": graph_nav, "llm_flat": llm_flat, "bm25": bm25}
LLM_METHODS = {"graph_nav", "llm_flat"}
