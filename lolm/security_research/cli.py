"""Offline command-line interface: analyze, simulate, benchmark, verify."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from .lab import analyze, benchmark, parse_jsonl, synthetic_scenarios, verify_receipts
from .headlines import headline_audit, parse_claims
from .ocsf import as_jsonl, map_jsonl


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LOLM defensive security research (offline only)")
    group = parser.add_subparsers(dest="cmd", required=True)
    analyze_cmd = group.add_parser("analyze", help="read local JSONL events")
    analyze_cmd.add_argument("path", type=Path)
    analyze_cmd.add_argument("--mode", choices=["rules", "shift", "hybrid"], default="hybrid")
    group.add_parser("benchmark", help="compare baselines on fictional data")
    simulate_cmd = group.add_parser("simulate", help="write synthetic JSONL fixtures")
    simulate_cmd.add_argument("path", type=Path)
    simulate_cmd.add_argument("--seed", type=int, default=37)
    ocsf_cmd = group.add_parser("ocsf-map", help="pseudonymize OCSF authentication records")
    ocsf_cmd.add_argument("path", type=Path)
    ocsf_cmd.add_argument("--salt-file", type=Path, required=True, help="local key bytes (>=16 bytes)")
    headlines_cmd = group.add_parser("headlines", help="audit cyber news claim provenance")
    headlines_cmd.add_argument("path", type=Path)
    headlines_cmd.add_argument("--since", required=True, help="ISO-8601 timestamp with timezone")
    verify_cmd = group.add_parser("verify", help="verify saved analysis receipt chain")
    verify_cmd.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    if args.cmd == "ocsf-map":
        with args.path.open("r", encoding="utf8") as stream:
            events, _counts = map_jsonl(stream, args.salt_file.read_bytes())
        print(as_jsonl(events), end="")
        return 0
    if args.cmd == "analyze":
        with args.path.open("r", encoding="utf8") as stream:
            result = analyze(parse_jsonl(stream), args.mode)
    elif args.cmd == "benchmark":
        result = benchmark()
    elif args.cmd == "headlines":
        with args.path.open("r", encoding="utf8") as stream:
            result = headline_audit(parse_claims(stream), args.since)
    elif args.cmd == "simulate":
        if args.path.exists():
            parser.error("refusing to overwrite existing path")
        args.path.write_text("\n".join(json.dumps(asdict(e), sort_keys=True) for e in synthetic_scenarios(args.seed)) + "\n", encoding="utf8")
        result = {"created": str(args.path), "data_origin": "fictional"}
    else:
        saved = json.loads(args.path.read_text(encoding="utf8"))
        ok = verify_receipts(saved["receipts"], saved["head"])
        result = {"valid": ok, "head": saved["head"]}
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if ok else 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
