"""Offline command-line interface: analyze, simulate, benchmark, verify."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from .lab import analyze, benchmark, parse_jsonl, synthetic_scenarios, verify_receipts
from .headlines import headline_audit, parse_claims
from .ocsf import as_jsonl, map_jsonl
from .observer import check_manifest, fit_benign, parse_tokens, shadow_evaluate
from .stress import stress_benchmark
from .fixtures import write_study
from .falsification import evaluate_falsification
from .stress import Case


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LOLM defensive security research (offline only)")
    group = parser.add_subparsers(dest="cmd", required=True)
    analyze_cmd = group.add_parser("analyze", help="read local JSONL events")
    analyze_cmd.add_argument("path", type=Path)
    analyze_cmd.add_argument("--mode", choices=["rules", "shift", "hybrid"], default="hybrid")
    group.add_parser("benchmark", help="compare baselines on fictional data")
    group.add_parser("stress", help="expose false positives on adversarial fictional data")
    study_cmd = group.add_parser("make-study", help="write split synthetic reference and held-out event sets")
    study_cmd.add_argument("out_dir", type=Path)
    study_cmd.add_argument("--reference-events", type=int, default=60)
    observe_cmd = group.add_parser("observe", help="score offline LOLM NFET token telemetry (shadow-only)")
    observe_cmd.add_argument("--train-events", type=Path, required=True)
    observe_cmd.add_argument("--train-trace", type=Path, required=True)
    observe_cmd.add_argument("--train-manifest", type=Path, required=True)
    observe_cmd.add_argument("--test-events", type=Path, required=True)
    observe_cmd.add_argument("--test-trace", type=Path, required=True)
    observe_cmd.add_argument("--test-manifest", type=Path, required=True)
    observe_cmd.add_argument("--ack-known-benign", action="store_true",
                             help="assert calibration events are verified benign, not merely unlabeled")
    observe_cmd.add_argument("--alpha", type=float, default=0.1)
    observe_cmd.add_argument("--checkpoint", type=Path, help="local checkpoint file; required for claimed checkpoint-generated traces")
    observe_cmd.add_argument("--expected-checkpoint", help="SHA-256 pin supplied independently of manifests")
    falsify_cmd = group.add_parser("falsify", help="run offline incident-label permutation and telemetry shuffle controls")
    falsify_cmd.add_argument("--train-events", type=Path, required=True)
    falsify_cmd.add_argument("--train-trace", type=Path, required=True)
    falsify_cmd.add_argument("--train-manifest", type=Path, required=True)
    falsify_cmd.add_argument("--test-events", type=Path, required=True)
    falsify_cmd.add_argument("--test-trace", type=Path, required=True)
    falsify_cmd.add_argument("--test-manifest", type=Path, required=True)
    falsify_cmd.add_argument("--scenarios", type=Path, required=True)
    falsify_cmd.add_argument("--ack-known-benign", action="store_true")
    falsify_cmd.add_argument("--alpha", type=float, default=0.1)
    falsify_cmd.add_argument("--checkpoint", type=Path)
    falsify_cmd.add_argument("--expected-checkpoint")
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
    elif args.cmd == "stress":
        result = stress_benchmark()
    elif args.cmd == "make-study":
        result = write_study(args.out_dir, args.reference_events)
    elif args.cmd in ("observe", "falsify"):
        if not args.ack_known_benign:
            parser.error("--ack-known-benign required; labels defaulting to false is not proof")
        def load_bundle(event_path, trace_path, manifest_path):
            with event_path.open("r", encoding="utf8") as handle:
                events = parse_jsonl(handle)
            with trace_path.open("r", encoding="utf8") as handle:
                tokens = parse_tokens(handle, len(events))
            manifest = json.loads(manifest_path.read_text(encoding="utf8"))
            return events, tokens, manifest
        train_events, train_tokens, train_manifest = load_bundle(
            args.train_events, args.train_trace, args.train_manifest)
        test_events, test_tokens, test_manifest = load_bundle(
            args.test_events, args.test_trace, args.test_manifest)
        if train_manifest.get("source_type") != test_manifest.get("source_type"):
            parser.error("train and test trace origins must match")
        if train_manifest.get("checkpoint_sha256") != test_manifest.get("checkpoint_sha256"):
            parser.error("train and test checkpoints must match")
        if train_manifest.get("source_type") == "checkpoint-generated":
            if args.checkpoint is None or args.expected_checkpoint is None:
                parser.error("checkpoint-generated traces require --checkpoint and independent --expected-checkpoint")
        if args.checkpoint is not None and args.expected_checkpoint is None:
            parser.error("--checkpoint requires --expected-checkpoint")
        train_provenance = check_manifest(train_manifest, train_events, train_tokens,
                                          checkpoint_path=args.checkpoint,
                                          expected_checkpoint=args.expected_checkpoint)
        test_provenance = check_manifest(test_manifest, test_events, test_tokens,
                                         checkpoint_path=args.checkpoint,
                                         expected_checkpoint=args.expected_checkpoint)
        if args.cmd == "observe":
            calibration = fit_benign(train_events, train_tokens, alpha=args.alpha)
            result = shadow_evaluate(calibration, train_events, test_events, test_tokens)
            result["reference_count"] = calibration.reference_count
            result["calibration_count"] = calibration.calibration_count
        else:
            raw = json.loads(args.scenarios.read_text(encoding="utf8"))
            if not isinstance(raw, list) or not 1 <= len(raw) <= 18:
                parser.error("scenario labels must contain 1..18 records")
            if any(not isinstance(row, dict) or set(row) != set(Case.__dataclass_fields__)
                   for row in raw):
                parser.error("scenario metadata must contain exactly the Case fields")
            scenarios = [Case(**row) for row in raw]
            result = evaluate_falsification(train_events, train_tokens,
                                            test_events, test_tokens, scenarios,
                                            alpha=args.alpha)
        result["train_provenance"] = train_provenance
        result["test_provenance"] = test_provenance
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
