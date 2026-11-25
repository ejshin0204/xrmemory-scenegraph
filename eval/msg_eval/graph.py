"""Memory scene graph (MSG) index: candidate nodes, edges, and the navigation functions
the retrieval agent calls.

Candidate nodes (what a retriever may return in its top-5):
  object         objects[]               id = object id (BTN_*, SCREEN_1, ...)
  state          states[]                id = state_01..  (states have no id in the JSON)
  event          events[]                id = event id
  observation    observations[]          id = observation id
  interpretation interpretations[]       id = interpretation id
  decision_point decision_graph.nodes[]  id = DP1..DP5

decision_graph UPDATE records only point at the nodes above (evidence_refs), so they are
navigated through, not returned. Relations are edges, not candidates.

The navigation functions follow Graph-CoT (Jin et al., Findings of ACL 2024): search a node by
text, read a node's features, list its neighbours by relation. Two functions are added for the
episodic part of the graph: a time-window read and a decision-point read.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CANDIDATE_TYPES = ("object", "state", "event", "observation", "interpretation", "decision_point")


@dataclass
class Node:
    id: str
    type: str
    subtype: str | None
    start_ms: int | None
    end_ms: int | None
    dp: str | None
    text: str          # one-line text used for search and display
    raw: dict[str, Any] = field(repr=False)
    pointer: str = ""  # JSON Pointer into the scene graph file


@dataclass
class Edge:
    source: str
    relation: str
    target: str


def _fmt_s(ms: int | None) -> str:
    return "-" if ms is None else f"{ms / 1000:.1f}s"


class MemorySceneGraph:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.g = json.loads(self.path.read_text(encoding="utf-8"))
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self._dp_windows: list[tuple[str, int, int]] = []
        self._build()

    # ------------------------------------------------------------------ build
    def _dp_of(self, ms: int | None) -> str | None:
        if ms is None:
            return None
        for dp, a, b in self._dp_windows:
            if a <= ms < b:
                return dp
        return self._dp_windows[-1][0] if self._dp_windows and ms >= self._dp_windows[-1][2] else None

    def _add(self, node: Node) -> None:
        if node.id in self.nodes:
            raise ValueError(f"duplicate node id {node.id}")
        self.nodes[node.id] = node

    def _build(self) -> None:
        g = self.g
        dg = g.get("decision_graph", {})
        for n in dg.get("nodes", []):
            w = n.get("observed_window") or {}
            if "start_ms" in w:
                self._dp_windows.append((n["id"], w["start_ms"], w["end_ms"]))

        # objects
        zone_of = {r["source"]: r["target"] for r in g.get("relations", []) if r["type"] == "part_of"}
        for i, o in enumerate(g.get("objects", [])):
            bits = [o.get("name", "")]
            if o.get("physical_key"):
                bits.append(f"physical_key={o['physical_key']}")
            if o["id"] in zone_of:
                bits.append(f"part_of={zone_of[o['id']]}")
            eff = (o.get("Affordance") or {}).get("effects")
            if eff:
                bits.append("effect=" + ", ".join(f"{e['object_id']}.{e['attribute']}→{e['value']}" for e in eff))
            if o.get("note"):
                bits.append(o["note"])
            if o.get("observed_label"):
                bits.append(o["observed_label"])
            self._add(Node(o["id"], "object", o.get("type"), None, None, None, " | ".join(bits), o, f"/objects/{i}"))

        # states (no ids in the JSON)
        for i, s in enumerate(g.get("states", [])):
            sid = f"state_{i + 1:02d}"
            text = (f"{s['object_id']}.{s['attribute']} = {s['value']!r}"
                    f" | task_state={s.get('task_state')} | phase={s.get('reported_phase')}")
            self._add(Node(sid, "state", s.get("attribute"), s.get("start_ms"), s.get("end_ms"),
                           self._dp_of(s.get("start_ms")), text, s, f"/states/{i}"))

        # events
        for i, e in enumerate(g.get("events", [])):
            bits = [e["type"]]
            for k in ("target_id", "physical_key", "key_group", "observed_effect", "description"):
                if e.get(k):
                    bits.append(f"{k}={e[k]}")
            self._add(Node(e["id"], "event", e["type"], e.get("time_ms"), e.get("end_ms"),
                           self._dp_of(e.get("time_ms")), " | ".join(bits), e, f"/events/{i}"))

        # observations / interpretations (think-aloud)
        for i, o in enumerate(g.get("observations", [])):
            self._add(Node(o["id"], "observation", o.get("cue"), o.get("start_ms"), o.get("end_ms"),
                           self._dp_of(o.get("start_ms")), o.get("text", ""), o, f"/observations/{i}"))
        for i, it in enumerate(g.get("interpretations", [])):
            bits = [it.get("text", "")]
            for k in ("stated_button_id", "trigger", "withheld_action_ids", "planned_action_ids", "monitor_cues"):
                if it.get(k):
                    bits.append(f"{k}={it[k]}")
            self._add(Node(it["id"], "interpretation", it.get("kind"), it.get("start_ms"), it.get("end_ms"),
                           self._dp_of(it.get("start_ms")), " | ".join(bits), it, f"/interpretations/{i}"))

        # decision points
        for i, n in enumerate(dg.get("nodes", [])):
            w = n.get("observed_window") or {}
            text = f"{n['label']} | {n['required_state']}→{n['target_state']}"
            if n.get("note"):
                text += f" | {n['note']}"
            self._add(Node(n["id"], "decision_point", None, w.get("start_ms"), w.get("end_ms"), n["id"],
                           text, n, f"/decision_graph/nodes/{i}"))

        self._build_edges()

    def _edge(self, s: str | None, rel: str, t: str | None) -> None:
        if s and t and s in self.nodes and t in self.nodes:
            self.edges.append(Edge(s, rel, t))

    def _build_edges(self) -> None:
        g = self.g
        for r in g.get("relations", []):
            self._edge(r["source"], r["type"], r["target"])
        for e in g.get("events", []):
            self._edge(e["id"], "targets", e.get("target_id"))
            self._edge(e["id"], "on_key_group", e.get("key_group"))
            self._edge(e["id"], "intent_stated_in", e.get("target_evidence"))
        for o in g.get("observations", []):
            self._edge(o["id"], "about_event", o.get("related_event_id"))
        for it in g.get("interpretations", []):
            for oid in it.get("observation_ids") or []:
                self._edge(it["id"], "based_on", oid)
            self._edge(it["id"], "selected_action", it.get("selected_action_id"))
            self._edge(it["id"], "states_button", it.get("stated_button_id"))
            for b in it.get("withheld_action_ids") or []:
                self._edge(it["id"], "withholds", b)
            for b in it.get("planned_action_ids") or []:
                self._edge(it["id"], "plans", b)
        # state <- button press that came right before it (same rule as build_scenegraph.py R1)
        presses = [n for n in self.nodes.values() if n.type == "event" and n.subtype == "button_press"]
        for s in (n for n in self.nodes.values() if n.type == "state"):
            self._edge(s.id, "of_object", s.raw.get("object_id"))
            hit = [p for p in presses if p.start_ms is not None and s.start_ms is not None
                   and 0 <= s.start_ms - p.start_ms <= 1000]
            if hit:
                self._edge(s.id, "caused_by_press", hit[-1].id)
        # decision points
        for e in g.get("decision_graph", {}).get("edges", []):
            if e["type"] == "NEXT":
                self._edge(e["source"], "next", e["target"])
        for n in self.nodes.values():
            if n.type != "decision_point" and n.dp:
                self._edge(n.id, "in_dp", n.dp)

    # ------------------------------------------------------------ navigation
    def overview(self) -> dict[str, Any]:
        """Function 0: what the graph holds (types, counts, decision-point windows, relation types)."""
        counts = Counter(n.type for n in self.nodes.values())
        rels = Counter(e.relation for e in self.edges)
        return {
            "scene_id": self.g.get("scene_id"), "trial_id": self.g.get("trial_id"),
            "scenario": self.g.get("scenario"),
            "time_unit": "ms from trial start",
            "node_counts": dict(counts),
            "relation_counts": dict(rels),
            "decision_points": [
                {"id": n.id, "label": n.raw["label"], "window": f"{_fmt_s(n.start_ms)}–{_fmt_s(n.end_ms)}"}
                for n in self.nodes.values() if n.type == "decision_point"],
        }

    def node_feature(self, node_id: str) -> dict[str, Any]:
        """Graph-CoT NodeFeature: all stored attributes of one node."""
        n = self.nodes.get(node_id)
        if n is None:
            return {"error": f"unknown node id {node_id}"}
        return {"id": n.id, "type": n.type, "subtype": n.subtype, "dp": n.dp,
                "start_s": None if n.start_ms is None else n.start_ms / 1000,
                "end_s": None if n.end_ms is None else n.end_ms / 1000,
                "attributes": n.raw}

    def neighbors(self, node_id: str, relation: str | None = None) -> list[dict[str, str]]:
        """Graph-CoT NeighborCheck: nodes linked to node_id (both directions), optionally one relation."""
        out = []
        for e in self.edges:
            if relation and e.relation != relation:
                continue
            if e.source == node_id:
                out.append({"relation": e.relation, "direction": "out", "id": e.target,
                            "type": self.nodes[e.target].type, "text": self.nodes[e.target].text[:160]})
            elif e.target == node_id:
                out.append({"relation": e.relation, "direction": "in", "id": e.source,
                            "type": self.nodes[e.source].type, "text": self.nodes[e.source].text[:160]})
        return out

    def time_window(self, start_s: float, end_s: float, types: list[str] | None = None) -> list[dict[str, Any]]:
        """Nodes whose time span overlaps [start_s, end_s], in time order."""
        a, b = start_s * 1000, end_s * 1000
        hits = []
        for n in self.nodes.values():
            if n.start_ms is None or (types and n.type not in types) or n.type == "decision_point":
                continue
            end = n.end_ms if n.end_ms is not None else n.start_ms
            if n.start_ms <= b and end >= a:
                hits.append(n)
        hits.sort(key=lambda n: n.start_ms)
        return [self.brief(n) for n in hits]

    def decision_point(self, dp_id: str) -> dict[str, Any]:
        """A decision point with its window and the nodes inside it, in time order."""
        n = self.nodes.get(dp_id)
        if n is None or n.type != "decision_point":
            return {"error": f"unknown decision point {dp_id}"}
        members = sorted((m for m in self.nodes.values() if m.dp == dp_id and m.type != "decision_point"),
                         key=lambda m: m.start_ms or 0)
        return {"id": dp_id, "label": n.raw["label"], "required_state": n.raw["required_state"],
                "target_state": n.raw["target_state"], "window": f"{_fmt_s(n.start_ms)}–{_fmt_s(n.end_ms)}",
                "note": n.raw.get("note"), "members": [self.brief(m) for m in members]}

    def brief(self, n: Node, width: int = 160) -> dict[str, Any]:
        t = n.text if len(n.text) <= width else n.text[:width] + "…"
        span = f"{_fmt_s(n.start_ms)}–{_fmt_s(n.end_ms)}" if n.start_ms is not None else None
        return {"id": n.id, "type": n.type, "subtype": n.subtype, "time": span, "dp": n.dp, "text": t}

    # ---------------------------------------------------------------- search
    def search(self, query: str, k: int = 10, types: list[str] | None = None) -> list[dict[str, Any]]:
        """Graph-CoT RetrieveNode: lexical BM25 over node text (Korean char bigrams + word tokens)."""
        scored = self._bm25.score(query)
        ranked = [(s, nid) for nid, s in scored.items()
                  if s > 0 and (not types or self.nodes[nid].type in types)]
        ranked.sort(reverse=True)
        return [{**self.brief(self.nodes[nid]), "score": round(s, 3)} for s, nid in ranked[:k]]

    @property
    def _bm25(self) -> "BM25":
        if not hasattr(self, "_bm25_index"):
            self._bm25_index = BM25({nid: n.id + " " + n.text for nid, n in self.nodes.items()})
        return self._bm25_index

    def candidate_ids(self) -> list[str]:
        return list(self.nodes)


# ------------------------------------------------------------------- BM25
_TOKEN = re.compile(r"[A-Za-z_]+[A-Za-z0-9_]*|[0-9]+(?:\.[0-9]+)?|[가-힣]+")


def tokenize(text: str) -> list[str]:
    toks = []
    for t in _TOKEN.findall(text.lower()):
        if re.fullmatch(r"[가-힣]+", t):
            toks.extend(t[i:i + 2] for i in range(max(1, len(t) - 1)))  # char bigrams cope with Korean particles
        else:
            toks.append(t)
    return toks


class BM25:
    def __init__(self, docs: dict[str, str], k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = {d: Counter(tokenize(t)) for d, t in docs.items()}
        self.len = {d: sum(c.values()) for d, c in self.tf.items()}
        self.avg = sum(self.len.values()) / max(1, len(self.len))
        df = defaultdict(int)
        for c in self.tf.values():
            for w in c:
                df[w] += 1
        n = len(self.tf)
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}

    def score(self, query: str) -> dict[str, float]:
        q = tokenize(query)
        out = {}
        for d, c in self.tf.items():
            s = 0.0
            for w in q:
                if w in c:
                    f = c[w]
                    s += self.idf[w] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[d] / self.avg))
            out[d] = s
        return out


# --------------------------------------------------------------------- CLI
if __name__ == "__main__":
    import argparse
    import csv
    import sys

    ap = argparse.ArgumentParser(description="Dump the candidate node table of a scene graph.")
    ap.add_argument("--graph", default="examples/aria_261104_test0/scenegraph.json")
    ap.add_argument("--csv", help="write the node table as CSV")
    ap.add_argument("--md", help="write the node table as Markdown")
    a = ap.parse_args()
    msg = MemorySceneGraph(a.graph)
    rows = [{"id": n.id, "type": n.type, "subtype": n.subtype or "", "start_s": "" if n.start_ms is None else f"{n.start_ms/1000:.1f}",
             "end_s": "" if n.end_ms is None else f"{n.end_ms/1000:.1f}", "dp": n.dp or "", "pointer": n.pointer, "text": n.text}
            for n in msg.nodes.values()]
    if a.csv:
        with open(a.csv, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)
    if a.md:
        with open(a.md, "w", encoding="utf-8") as f:
            f.write(f"# Candidate nodes: {msg.g.get('trial_id')} ({len(rows)} nodes)\n\n")
            f.write("| id | type | subtype | time (s) | dp | text |\n|---|---|---|---|---|---|\n")
            for r in rows:
                t = f"{r['start_s']}–{r['end_s']}" if r["start_s"] else ""
                f.write(f"| {r['id']} | {r['type']} | {r['subtype']} | {t} | {r['dp']} | {r['text'].replace('|', '/')} |\n")
    print(json.dumps(msg.overview(), ensure_ascii=False, indent=1), file=sys.stderr)
