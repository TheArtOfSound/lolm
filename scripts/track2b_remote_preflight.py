#!/usr/bin/env python3
# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Preflight gate for the remote Track 2B 30-task qualification.

Run from a **fresh clone or clean CI workspace** only — never from a worktree
contaminated by untracked trees (e.g. snake-game/).

Usage:
  # Local workspace checks only (no network):
  python3 scripts/track2b_remote_preflight.py --workspace-only \\
      --expected-sha f1bd33f920cb552f281c6d829633ee2ef7feda34

  # Full remote preflight (requires staging + env):
  export LOLM_LIVE_BASE_URL=https://<sha-pinned-staging>
  export LOLM_LIVE_API_KEY=...          # env only; never print
  export LOLM_EXPECTED_SERVER_SHA=...
  export LOLM_EXPECTED_DEPLOYMENT_ID=...
  export LOLM_RECEIPT_VERIFY_KEYS='kid:pubkey'
  export LOLM_EXPECTED_RECEIPT_KEY_ID=kid
  export LOLM_EXPECTED_RECEIPT_PUBLIC_KEY_SHA256=...
  python3 scripts/track2b_remote_preflight.py --full

Exit 0 only when every required check passes.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Merge of PR #15 into grok/grand-audit-remediation — validation baseline.
DEFAULT_VALIDATION_SHA = "f1bd33f920cb552f281c6d829633ee2ef7feda34"

# Paths that must never appear as untracked contamination before a campaign.
CONTAMINATION_HINTS = (
    "snake-game",
    "snake-game.receipt.json",
)


def _run(cmd: List[str], cwd: Optional[Path] = None) -> Tuple[int, str]:
    p = subprocess.run(
        cmd, cwd=str(cwd or ROOT), capture_output=True, text=True,
    )
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode, out.strip()


def check_workspace(expected_sha: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    code, head = _run(["git", "rev-parse", "HEAD"])
    ok = code == 0 and head == expected_sha
    rows.append({
        "check": "checked_out_sha",
        "ok": ok,
        "expected": expected_sha,
        "actual": head if code == 0 else f"git_error:{head[:80]}",
    })

    code, porcelain = _run(["git", "status", "--porcelain"])
    clean = code == 0 and porcelain == ""
    rows.append({
        "check": "working_tree_clean",
        "ok": clean,
        "actual": "clean" if clean else porcelain[:500],
    })

    # Contamination: untracked or present paths that bias repo maps / fixtures
    contaminated = []
    for name in CONTAMINATION_HINTS:
        if (ROOT / name).exists():
            contaminated.append(name)
    rows.append({
        "check": "no_worktree_contamination",
        "ok": len(contaminated) == 0,
        "actual": contaminated or "none",
    })

    # Adaptive routing hard-off
    try:
        from lolm.shadow_telemetry import ADAPTIVE_ROUTING_ENABLED, adaptive_routing_active
        adaptive_off = (ADAPTIVE_ROUTING_ENABLED is False) and (not adaptive_routing_active())
    except Exception as exc:
        adaptive_off = False
        rows.append({
            "check": "adaptive_routing_off",
            "ok": False,
            "actual": f"import_error:{exc}",
        })
    else:
        rows.append({
            "check": "adaptive_routing_off",
            "ok": adaptive_off,
            "actual": {
                "ADAPTIVE_ROUTING_ENABLED": ADAPTIVE_ROUTING_ENABLED,
                "adaptive_routing_active": adaptive_routing_active(),
            },
        })

    # Runner must not hold private signing keys (unless local smoke flag — forbidden for remote)
    signing = os.environ.get("LOLM_RECEIPT_SIGNING_KEYS", "").strip()
    allow_untrusted = os.environ.get("LOLM_ALLOW_UNTRUSTED_LOCAL_RECEIPTS", "").strip() in (
        "1", "true", "yes",
    )
    rows.append({
        "check": "private_signing_key_not_on_runner",
        "ok": not signing or allow_untrusted,  # remote full preflight forbids both later
        "actual": "present" if signing else "absent",
        "note": "Remote --full forbids SIGNING_KEYS entirely",
    })

    return rows


def check_remote_env() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    required = {
        "LOLM_LIVE_BASE_URL": os.environ.get("LOLM_LIVE_BASE_URL", "").strip(),
        "LOLM_LIVE_API_KEY": os.environ.get("LOLM_LIVE_API_KEY") or os.environ.get("QIRA_API_KEY") or "",
        "LOLM_EXPECTED_SERVER_SHA": os.environ.get("LOLM_EXPECTED_SERVER_SHA", "").strip(),
        "LOLM_EXPECTED_DEPLOYMENT_ID": os.environ.get("LOLM_EXPECTED_DEPLOYMENT_ID", "").strip(),
        "LOLM_RECEIPT_VERIFY_KEYS": os.environ.get("LOLM_RECEIPT_VERIFY_KEYS", "").strip(),
        "LOLM_EXPECTED_RECEIPT_KEY_ID": os.environ.get("LOLM_EXPECTED_RECEIPT_KEY_ID", "").strip(),
        "LOLM_EXPECTED_RECEIPT_PUBLIC_KEY_SHA256": os.environ.get(
            "LOLM_EXPECTED_RECEIPT_PUBLIC_KEY_SHA256", ""
        ).strip(),
    }
    for name, val in required.items():
        secret = "KEY" in name or "SECRET" in name
        rows.append({
            "check": f"env_{name}",
            "ok": bool(val),
            "actual": ("set" if val else "unset") if secret else (val or "unset"),
        })

    transport = os.environ.get("LOLM_LIVE_TRANSPORT", "lolm-code-sse").strip()
    rows.append({
        "check": "transport_lolm_code_sse",
        "ok": transport == "lolm-code-sse",
        "actual": transport,
    })

    allow = os.environ.get("LOLM_ALLOW_UNTRUSTED_LOCAL_RECEIPTS", "").strip() in (
        "1", "true", "yes",
    )
    rows.append({
        "check": "untrusted_local_receipts_disabled",
        "ok": not allow,
        "actual": allow,
    })

    signing = os.environ.get("LOLM_RECEIPT_SIGNING_KEYS", "").strip()
    rows.append({
        "check": "no_private_signing_keys_on_runner",
        "ok": not signing,
        "actual": "present" if signing else "absent",
    })

    adaptive_env = os.environ.get("LOLM_ADAPTIVE_ROUTING", "").strip().lower()
    rows.append({
        "check": "adaptive_routing_env_off",
        "ok": adaptive_env in ("", "0", "false", "off", "no"),
        "actual": adaptive_env or "(unset)",
    })

    return rows


def check_staging_identity(
    base_url: str,
    api_key: str,
    expected_sha: str,
    expected_deployment: str,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    base = base_url.rstrip("/")

    # Prefer /health or /api/demo/status for identity probe (no secrets in output)
    body: Dict[str, Any] = {}
    status_code = 0
    for path in ("/health", "/api/demo/status"):
        url = base + path
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "lolm-track2b-preflight/1",
                    "X-LOLM-Api-Key": api_key,
                    "Accept": "application/json",
                },
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                status_code = getattr(resp, "status", 200)
                raw = resp.read(8000).decode("utf-8", "replace")
            try:
                body = json.loads(raw)
            except Exception:
                body = {"_raw": raw[:200]}
            break
        except urllib.error.HTTPError as e:
            status_code = e.code
            try:
                body = json.loads(e.read().decode("utf-8", "replace"))
            except Exception:
                body = {"error": f"http_{e.code}"}
        except Exception as e:
            status_code = 0
            body = {"error": type(e).__name__}

    rows.append({
        "check": "staging_reachable",
        "ok": status_code == 200,
        "actual": status_code,
    })

    server_sha = str(
        body.get("server_sha")
        or body.get("git_sha")
        or body.get("sha")
        or (body.get("build") or {}).get("sha")
        or ""
    )
    rows.append({
        "check": "server_reported_sha",
        "ok": bool(server_sha) and server_sha == expected_sha,
        "expected": expected_sha,
        "actual": server_sha or body,
    })

    dep = str(
        body.get("deployment_id")
        or (body.get("build") or {}).get("deployment_id")
        or ""
    )
    rows.append({
        "check": "deployment_id",
        "ok": (not expected_deployment) or (dep == expected_deployment),
        "expected": expected_deployment or "(any if unset)",
        "actual": dep or "(missing)",
    })

    # Isolation: status may report bwrap / isolated
    iso = str(
        body.get("isolation")
        or body.get("isolated")
        or (body.get("limits") or {}).get("isolated")
        or body.get("bwrap")
        or ""
    ).lower()
    iso_ok = any(x in iso for x in ("bwrap", "true", "1", "namespace", "jail")) if iso else False
    # Also accept explicit env confirmation from deploy probe
    if os.environ.get("LOLM_BWRAP_CONFIRMED", "").strip() in ("1", "true", "yes"):
        iso_ok = True
        iso = iso or "LOLM_BWRAP_CONFIRMED=1"
    rows.append({
        "check": "isolation_bwrap",
        "ok": iso_ok,
        "actual": iso or "(not reported — set LOLM_BWRAP_CONFIRMED=1 after ops verification)",
        "required": "bwrap",
    })

    # Route existence: OPTIONS/POST probe without starting a full agent run
    route = "/api/demo/code/run"
    route_ok = False
    route_detail = ""
    try:
        req = urllib.request.Request(
            base + route,
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "X-LOLM-Api-Key": api_key,
                "Accept": "text/event-stream, application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            route_detail = f"status={getattr(resp, 'status', '?')}"
            # 200 SSE or 400 empty task both prove the product route exists
            route_ok = True
    except urllib.error.HTTPError as e:
        # 400/422 empty body, 401 wrong key shape, 503 no bwrap — route exists
        route_ok = e.code in (400, 401, 403, 422, 429, 503)
        route_detail = f"http_{e.code}"
        if e.code == 404:
            route_ok = False
    except Exception as e:
        route_detail = type(e).__name__
        route_ok = False
    rows.append({
        "check": "route_api_demo_code_run",
        "ok": route_ok,
        "actual": route_detail,
        "required": route,
    })

    # Model/provider emission is verified on first admitted run; preflight only
    # records that the campaign will require them.
    rows.append({
        "check": "model_provider_identity_required_in_receipts",
        "ok": True,
        "actual": "enforced by campaign adapter + evidence capture",
    })

    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Track 2B remote campaign preflight")
    ap.add_argument(
        "--expected-sha",
        default=os.environ.get("LOLM_EXPECTED_SERVER_SHA") or DEFAULT_VALIDATION_SHA,
    )
    ap.add_argument("--workspace-only", action="store_true")
    ap.add_argument("--full", action="store_true", help="workspace + env + staging identity")
    ap.add_argument(
        "--out",
        default="",
        help="optional JSON report path",
    )
    args = ap.parse_args()
    if not args.workspace_only and not args.full:
        args.workspace_only = True

    results: List[Dict[str, Any]] = []
    results.extend(check_workspace(args.expected_sha))

    if args.full:
        results.extend(check_remote_env())
        base = os.environ.get("LOLM_LIVE_BASE_URL", "").strip()
        key = (
            os.environ.get("LOLM_LIVE_API_KEY")
            or os.environ.get("QIRA_API_KEY")
            or ""
        ).strip()
        exp_sha = os.environ.get("LOLM_EXPECTED_SERVER_SHA", args.expected_sha).strip()
        exp_dep = os.environ.get("LOLM_EXPECTED_DEPLOYMENT_ID", "").strip()
        if base and key:
            results.extend(check_staging_identity(base, key, exp_sha, exp_dep))
        else:
            results.append({
                "check": "staging_identity_probe",
                "ok": False,
                "actual": "missing LOLM_LIVE_BASE_URL or API key",
            })

    failed = [r for r in results if not r.get("ok")]
    report = {
        "schema": "lolm.track2b.preflight.v1",
        "mode": "full" if args.full else "workspace_only",
        "expected_sha": args.expected_sha,
        "passed": len(failed) == 0,
        "failed_count": len(failed),
        "checks": results,
        "outcome_classes": {
            "inadmissible": "infrastructure or identity mismatch",
            "agent_failure": "wrong diagnosis, failed repair, timeout after admission",
            "trust_abort": "blind/stale mutation applied or false-green shipment",
        },
        "promotion_to_150_requires": {
            "trust_aborts": 0,
            "blind_mutations_applied": 0,
            "stale_mutations_applied": 0,
            "false_green_shipments": 0,
            "receipt_signature_mismatches": 0,
            "secret_leaks": 0,
            "competence_threshold": "predetermined",
        },
        "adaptive_routing": "disabled",
    }

    text = json.dumps(report, indent=2)
    # Never echo API keys
    key = os.environ.get("LOLM_LIVE_API_KEY") or os.environ.get("QIRA_API_KEY") or ""
    if key and len(key) >= 8 and key in text:
        text = text.replace(key, "***REDACTED***")

    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n", encoding="utf-8")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
