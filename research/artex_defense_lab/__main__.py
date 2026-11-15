"""Offline-only CLI. Absolutely no shell/network execution or target input."""
import argparse
from pathlib import Path
import json
from .scenarios import generate
from .evaluate import evaluate, html_report
from .core import advisory_from_nfet


def write_jsonl(path, records):
    with path.open('w', encoding='utf-8') as fd:
        for record in records:
            fd.write(json.dumps(record, sort_keys=True) + '\n')


def read_jsonl(path, max_items=100_000):
    with path.open('r', encoding='utf-8') as fd:
        results = []
        for line in fd:
            if len(results) >= max_items:
                raise ValueError('too many JSONL records')
            if len(line) > 8192:
                raise ValueError('JSONL line too large')
            if line.strip():
                results.append(json.loads(line))
        return results


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m research.artex_defense_lab',
                                     description='LOLM isolated, simulated security detector lab')
    subs = parser.add_subparsers(dest='command', required=True)
    generate_cmd = subs.add_parser('generate', help='Generate fake logs and separate truth labels')
    generate_cmd.add_argument('--out', type=Path, default=Path('out/artex-defense'))
    generate_cmd.add_argument('--seed', type=int, default=20261115)
    generate_cmd.add_argument('--repeats', type=int, default=8)
    eval_cmd = subs.add_parser('evaluate', help='Evaluate two safe detection baselines')
    eval_cmd.add_argument('--input', type=Path, default=Path('out/artex-defense'))
    eval_cmd.add_argument('--out', type=Path, default=Path('out/artex-defense'))
    nfet_cmd = subs.add_parser('nfet-advisory', help='Parse externally produced LOLM monitoring JSON')
    nfet_cmd.add_argument('--input', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == 'generate':
        events, labels = generate(args.seed, args.repeats)
        args.out.mkdir(parents=True, exist_ok=True)
        write_jsonl(args.out / 'events.jsonl', events)
        write_jsonl(args.out / 'labels.jsonl', labels)
        print(f'Generated {len(events)} fake events in {len(labels)} cases; {args.out}')
    elif args.command == 'evaluate':
        events = read_jsonl(args.input / 'events.jsonl')
        labels = read_jsonl(args.input / 'labels.jsonl')
        result = evaluate(events, labels)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / 'results.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        (args.out / 'report.html').write_text(html_report(result), encoding='utf-8')
        for mode, r in result['results'].items():
            print(f'{mode:12} P={r["precision"]:.3f} R={r["recall"]:.3f} F1={r["f1"]:.3f} FP={r["fp"]} FN={r["fn"]}')
        print('Real LOLM model executed: False; network actions performed: False')
        print(f'Report: {args.out / "report.html"}')
    elif args.command == 'nfet-advisory':
        data = json.loads(args.input.read_text(encoding='utf-8'))
        print(json.dumps(advisory_from_nfet(data), indent=2))

if __name__ == '__main__':
    main()
