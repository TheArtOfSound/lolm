"""Create disjoint fictional benign-reference and held-out test event sets.

Not operational telemetry. Event labels and actor identifiers must never reach
the checkpoint prompt; lolm.security_research.capture enforces this separately.
"""
from __future__ import annotations
from dataclasses import asdict
import json
from pathlib import Path
from .lab import Event
from .stress import cases


def known_benign_reference(n: int = 60) -> list[Event]:
    if not 40 <= n <= 200:
        raise ValueError("reference size must be 40-200 events")
    choices = ("ordinary_action", "login_success", "http_request")
    return [Event(1_840_000_000 + 19*i, f"fictional-ref-{i%5}", choices[i%3],
                  source="synthetic",truth=False) for i in range(n)]


def study_events(n: int = 60) -> tuple[list[Event],list[Event]]:
    train = known_benign_reference(n)
    test, _ = cases()
    if any(e.ts >= test[0].ts for e in train):
        raise ValueError("reference must precede held-out scenario timestamps")
    return train,test


def write_study(directory: Path, n: int = 60) -> dict:
    if directory.exists():
        raise FileExistsError("refusing to overwrite study directory")
    train,test = study_events(n)
    _,scenarios = cases()
    directory.mkdir(parents=True,exist_ok=False)
    for name,items in (("reference-events.jsonl",train),("heldout-events.jsonl",test)):
        (directory/name).write_text(
            "".join(json.dumps(asdict(e),sort_keys=True)+"\n" for e in items),encoding="utf8")
    (directory/"scenario-labels.json").write_text(json.dumps([asdict(x) for x in scenarios],indent=2)+"\n",encoding="utf8")
    (directory/"README.txt").write_text(
        "Fictional synthetic defensive security study. Reference is known benign; "
        "held-out contains 3 suspicious and 5 benign scenarios. No results from this "
        "data establish operational cybersecurity accuracy. Do not include truth, actor "
        "names or freeform text in model prompts.\n",encoding="utf8")
    return {
        "reference_events":len(train),"test_events":len(test),
        "reference_path":str(directory/"reference-events.jsonl"),
        "heldout_path":str(directory/"heldout-events.jsonl"),
        "scenario_labels":str(directory/"scenario-labels.json"),
        "data_origin":"fictional",
    }
