"""Case-level scoring, provenance-aware receipts, and safe static HTML report."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
from html import escape
import hashlib
import json
from .core import Analyzer, Event, evidence_digest


def evaluate(events_raw: list[dict], labels: list[dict]) -> dict:
    events = [Event.parse(row) for row in events_raw]
    label_map: dict[str, dict] = {}
    for label in labels:
        if set(label) != {'case_id', 'attack', 'pattern'} or type(label['attack']) is not bool:
            raise ValueError('invalid label')
        if label['case_id'] in label_map:
            raise ValueError('duplicate case label')
        label_map[label['case_id']] = label
    grouped: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        grouped[event.case_id].append(event)
    if set(grouped) != set(label_map):
        raise ValueError('cases must match truth labels exactly')
    totals = {}
    all_findings = {}
    for mode in ['stateless', 'correlated']:
        findings = Analyzer(mode).run(events)
        flagged: dict[str, int] = {}
        for finding in findings:
            flagged[finding.case_id] = min(finding.minute, flagged.get(finding.case_id, 10**10))
        tp = fp = tn = fn = 0
        leads = []
        patterns: dict[str, dict[str, int]] = defaultdict(lambda: {'tp':0,'fp':0,'tn':0,'fn':0})
        for case_id, label in label_map.items():
            truth = label['attack']
            prediction = case_id in flagged
            outcome = 'tp' if truth and prediction else 'fn' if truth else 'fp' if prediction else 'tn'
            if outcome == 'tp':
                tp += 1
                leads.append(max(e.minute for e in grouped[case_id]) - flagged[case_id])
            elif outcome == 'fp': fp += 1
            elif outcome == 'tn': tn += 1
            else: fn += 1
            patterns[label['pattern']][outcome] += 1
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        totals[mode] = {
            'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn,
            'precision': round(precision, 4), 'recall': round(recall, 4),
            'f1': round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
            'mean_minutes_before_case_end': round(sum(leads) / len(leads), 2) if leads else None,
            'patterns': dict(patterns),
        }
        all_findings[mode] = [f.as_dict() for f in findings]
    digest = evidence_digest(sorted(events, key=lambda e: (e.case_id, e.minute, e.event_id)))
    receipt = {
        'schema': 'lolm-defense-benchmark/v1', 'dataset_sha256': digest,
        'case_count': len(label_map), 'event_count': len(events),
        'method': 'synthetic_case_level_labels', 'real_lolm_model_executed': False,
        'network_actions_performed': False, 'results': totals,
        'findings': all_findings,
    }
    # A digest over the receipt's deterministic content, without a signature claim.
    content = json.dumps(receipt, sort_keys=True, separators=(',', ':'))
    receipt['content_sha256'] = hashlib.sha256(content.encode()).hexdigest()
    return receipt


def html_report(receipt: dict) -> str:
    rows = []
    for mode, r in receipt['results'].items():
        bars = f'<div class="track"><div class="fill" style="width:{r["f1"] * 100:.1f}%"></div></div>'
        rows.append(f'<tr><td>{escape(mode)}</td><td>{r["precision"]:.3f}</td><td>{r["recall"]:.3f}</td><td>{r["f1"]:.3f}{bars}</td><td>{r["fp"]}</td><td>{r["fn"]}</td></tr>')
    cells = '\n'.join(rows)
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LOLM Security Research — Offline Evaluation</title>
<style>
:root{{--bg:#0e1117;--panel:#171c25;--fg:#ecf0f7;--muted:#9aa7ba;--stroke:#303846;--accent:#72d6bd}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,sans-serif}}main{{max-width:960px;margin:0 auto;padding:56px 22px}}.eyebrow{{font:700 12px/1.4 ui-monospace,monospace;letter-spacing:.15em;color:var(--accent)}}h1{{font-size:clamp(28px,5vw,48px);letter-spacing:-.04em;line-height:1.1;margin:16px 0}}.lede{{max-width:70ch;color:var(--muted)}}.metrics{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:30px 0}}.metric{{background:var(--panel);padding:20px;border:1px solid var(--stroke);border-radius:10px}}.metric strong{{display:block;font-size:27px;font-variant-numeric:tabular-nums}}.metric span{{font-size:12px;color:var(--muted)}}section{{margin-top:40px}}table{{border-collapse:collapse;width:100%;background:var(--panel);border:1px solid var(--stroke);border-radius:8px}}th,td{{padding:13px;text-align:left;border-bottom:1px solid var(--stroke);font-variant-numeric:tabular-nums}}th{{font-size:12px;color:var(--muted)}}.track{{margin-top:6px;background:#303846;height:4px;width:110px;border-radius:9px}}.fill{{background:var(--accent);height:4px;border-radius:9px}}code{{color:#c9e9e1;word-break:break-all}}small{{color:var(--muted)}}@media(max-width:620px){{.metrics{{grid-template-columns:1fr}}table{{font-size:12px}}th,td{{padding:8px}}.track{{width:55px}}}}
</style><main><p class="eyebrow">QIRA / LOLM / DEFENSIVE RESEARCH 001</p><h1>Can memory detect an attack before isolated events can?</h1><p class="lede">Reproducible, completely synthetic case-level replay. This is a rule-based engineering baseline—not a measured result for the trained LOLM model. No network targets were contacted.</p><div class="metrics"><div class="metric"><strong>{receipt['case_count']}</strong><span>Synthetic incident timelines</span></div><div class="metric"><strong>{receipt['event_count']}</strong><span>Simulated log events</span></div><div class="metric"><strong>0</strong><span>Live targets contacted</span></div></div><section><h2>Detector comparison</h2><table><thead><tr><th>Detector</th><th>Precision</th><th>Recall</th><th>F1</th><th>False alarms</th><th>Misses</th></tr></thead><tbody>{cells}</tbody></table><p><small>All cases are scripted and class labels are separate from detector inputs. Higher performance on these fixtures does not establish generalization.</small></p></section><section><h2>Reproducibility receipt</h2><p><small>Dataset SHA-256</small><br><code>{escape(receipt['dataset_sha256'])}</code></p><p><small>Report content SHA-256</small><br><code>{escape(receipt['content_sha256'])}</code></p><p><small>Method: {escape(receipt['method'])}. Real LOLM model executed: no.</small></p></section></main></html>'''
