"""Native LOLM-304M telemetry capture for FICTIONAL SOC events only.

Distinct from a Qwen NFET graft. No internet, live scanning, attacker tools
or real account telemetry. Requires a trusted full LOLM checkpoint and local
LOLM source, torch, PyYAML and tiktoken.

python scripts/capture_security_lolm_native.py \
  --events runs/security_lab/study_001/reference-events.jsonl \
  --checkpoint /trusted/ckpt_26000.pt \
  --expected-sha <independently-verified-sha256> \
  --out-dir runs/security_lab/native_reference
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

from lolm.security_research.lab import parse_jsonl
from lolm.security_research.native_capture import capture_native
from lolm.security_research.observer import HEX256, check_manifest


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as reader:
        for chunk in iter(lambda: reader.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def validate_checkpoint(path: Path, expected: str) -> None:
    if not isinstance(expected, str) or not HEX256.fullmatch(expected):
        raise ValueError('expected SHA-256 must be a lowercase 64-hex independent pin')
    if not path.is_file():
        raise ValueError('checkpoint file unavailable')
    if file_sha256(path) != expected:
        raise ValueError('checkpoint SHA-256 mismatch: aborting before deserialization')


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--expected-sha', required=True)
    parser.add_argument('--config', default='configs/scale/300m_lolm_full_tpu.yaml')
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--device', choices=('cpu','mps','cuda'), default='cpu')
    parser.add_argument('--seed', type=int, default=20261115)
    parser.add_argument('--max-tokens', type=int, default=96)
    args=parser.parse_args()
    if args.out_dir.exists():
        parser.error('refusing to overwrite existing output directory')
    validate_checkpoint(args.checkpoint, args.expected_sha)
    with args.events.open('r',encoding='utf8') as handle:
        events=parse_jsonl(handle)
    if not events or len(events)>200 or any(e.source != 'synthetic' for e in events):
        parser.error('only 1..200 strictly fictional event records are allowed')

    import torch
    import tiktoken
    from lolm.config import load_config
    from lolm.model import LOLM

    if args.device == 'cuda' and not torch.cuda.is_available():
        parser.error('CUDA is unavailable')
    if args.device == 'mps' and not (hasattr(torch.backends,'mps') and torch.backends.mps.is_available()):
        parser.error('Apple MPS is unavailable')
    config=load_config(args.config)
    model=LOLM(config.model)
    # Do not use weights_only=False or strict=False: partially loaded models
    # may silently retain random weights and invalidate experiments.
    snapshot=torch.load(str(args.checkpoint),map_location='cpu',weights_only=True)
    if not isinstance(snapshot,dict) or 'model' not in snapshot or not isinstance(snapshot['model'],dict):
        raise RuntimeError('expected trusted checkpoint dict with model tensor state')
    model.load_state_dict(snapshot['model'],strict=True)
    model=model.to(args.device).eval()
    tokenizer=tiktoken.get_encoding('gpt2')
    started=time.monotonic()
    tokens,manifest=capture_native(events,model,tokenizer,checkpoint_sha256=args.expected_sha,
                                   device=args.device,run_seed=args.seed,max_tokens=args.max_tokens)
    seconds=round(time.monotonic()-started,3)
    checked=check_manifest(manifest,events,tokens,checkpoint_path=args.checkpoint,
                           expected_checkpoint=args.expected_sha)
    manifest.update({
        'config':args.config,'tokenizer':'tiktoken:gpt2','device':args.device,
        'model_parameters':model.count_parameters()['total'],
        'runtime_seconds':seconds,'checkpoint_bytes_verified':checked['checkpoint_bytes_verified'],
        'strict_weight_loading':True,'trace_origin_attested':False,
    })
    args.out_dir.mkdir(parents=True,exist_ok=False)
    (args.out_dir/'events.jsonl').write_text(''.join(json.dumps(asdict(e),sort_keys=True)+'\n' for e in events),encoding='utf8')
    (args.out_dir/'trace.jsonl').write_text(''.join(json.dumps(asdict(t),sort_keys=True)+'\n' for t in tokens),encoding='utf8')
    (args.out_dir/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n',encoding='utf8')
    print(json.dumps({'output':str(args.out_dir),'events':len(events),'tokens':len(tokens),
                      'model_family':'native-LOLM','runtime_seconds':seconds,
                      'checkpoint_bytes_verified':True,'trace_origin_attested':False},indent=2))


if __name__=='__main__':
    main()
