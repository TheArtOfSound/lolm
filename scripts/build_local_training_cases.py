#!/usr/bin/env python3
"""Build LOLM-NFET local training cases from the improvement log.

This is the first Hellhound-style self-reflection bridge:
chat traces + feedback -> ranked review queue -> adapter training cases.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def append_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def rank_chat(chat: Dict[str, Any], feedback: List[Dict[str, Any]]) -> tuple[int, List[str]]:
    score = 0
    reasons: List[str] = []
    summary = chat.get("summary", {}) or {}
    if any(x.get("rating") == "bad" for x in feedback):
        score += 10
        reasons.append("bad user feedback")
    if any(x.get("rating") == "good" for x in feedback):
        score += 2
        reasons.append("good preference example")
    if chat.get("last_graft_error"):
        score += 8
        reasons.append("graft error")
    if not chat.get("use_graft"):
        score += 6
        reasons.append("graft inactive")
    latent = summary.get("avg_latent_share")
    if latent is not None and latent < 0.15:
        score += 2
        reasons.append("low latent contribution")
    if summary.get("last_control") in {"verify", "branch"}:
        score += 1
        reasons.append("NFET uncertainty/control activity")
    if not reasons:
        reasons.append("normal review")
    return score, reasons


def build_cases(log_path: Path, out_path: Path, limit: int) -> List[Dict[str, Any]]:
    rows = read_jsonl(log_path)
    feedback_by_id: Dict[str, List[Dict[str, Any]]] = {}
    chats: List[Dict[str, Any]] = []
    for row in rows:
        if row.get("type") == "feedback":
            feedback_by_id.setdefault(str(row.get("entry_id")), []).append(row)
        elif row.get("type") == "chat":
            chats.append(row)

    ranked = []
    for chat in chats:
        entry_id = str(chat.get("id"))
        feedback = feedback_by_id.get(entry_id, [])
        score, reasons = rank_chat(chat, feedback)
        ranked.append((score, chat.get("timestamp") or 0, reasons, chat, feedback))
    ranked.sort(reverse=True, key=lambda x: (x[0], x[1]))

    cases: List[Dict[str, Any]] = []
    for score, _ts, reasons, chat, feedback in ranked[:limit]:
        note = "; ".join([str(f.get("note", "")) for f in feedback if f.get("note")]).strip()
        cases.append({
            "type": "training_case",
            "id": f"case-{int(time.time() * 1000)}-{len(cases)}",
            "source_entry_id": chat.get("id"),
            "priority": score,
            "reasons": reasons,
            "created_at": time.time(),
            "prompt": chat.get("prompt"),
            "response": chat.get("response"),
            "preferred_response": chat.get("response"),
            "correction_note": note,
            "feedback": feedback,
            "trace_summary": chat.get("summary"),
            "profile": chat.get("profile"),
        })
    append_jsonl(out_path, cases)
    return cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", default="local_ui/data/improvement_log.jsonl")
    parser.add_argument("--out", default="local_ui/data/training_cases.jsonl")
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    cases = build_cases(Path(args.log), Path(args.out), args.limit)
    print(json.dumps({"created": len(cases), "out": args.out}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
