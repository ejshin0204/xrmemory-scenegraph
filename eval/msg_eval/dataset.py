"""Load the in-graph gold QA set (eval/data/qa_ingraph.csv)."""
from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class QAItem:
    qid: str
    question: str
    answer: str
    gold_2: list[str]
    gold_1: list[str]
    qtype: str
    origin: str
    step: str
    button: str
    scenario_ref: str = ""   # e.g. "S4 내부 T5 [After Condition 판단]" (scenario script = main source)

    @property
    def scenario_step(self) -> str:
        """Leading step token of scenario_ref (S0..S6), '' if none."""
        return self.scenario_ref.split()[0] if self.scenario_ref else ""


def _ids(cell: str | None) -> list[str]:
    return [x.strip() for x in (cell or "").split(";") if x.strip()]


def load(path: str | Path, valid_ids: set[str] | None = None) -> list[QAItem]:
    items = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            it = QAItem(row["qid"], row["question"], row.get("answer", ""), _ids(row.get("gold_2")),
                        _ids(row.get("gold_1")), row.get("qtype", ""), row.get("origin", ""),
                        row.get("step", ""), row.get("button", ""), row.get("scenario_ref", "") or "")
            if not it.gold_2:
                raise ValueError(f"{it.qid}: empty gold_2")
            if valid_ids is not None:
                bad = [g for g in it.gold_2 + it.gold_1 if g not in valid_ids]
                if bad:
                    raise ValueError(f"{it.qid}: unknown gold ids {bad}")
            items.append(it)
    return items


def file_sha(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]
