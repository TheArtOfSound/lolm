# Copyright (c) 2026 Qira LLC. All rights reserved.
"""Developer API keys for integrate-anywhere.

Identity for usage quotas when present:
  Header:  X-LOLM-Api-Key: lolm_<key_id>_<secret>
  or:      Authorization: Bearer lolm_<key_id>_<secret>

Keys are stored as SHA-256 of the full token (never plaintext after mint).
Free keys: mint with IP rate limit. Paid keys: require a matching Stripe license
tier (or higher) on the request.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_LOCK = threading.Lock()
_PATH: Optional[Path] = None
_CREATE_LOG: Dict[str, List[float]] = {}  # ip -> timestamps


def init(root: Path) -> None:
    global _PATH
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    _PATH = root / "api_keys.json"
    if not _PATH.exists():
        _PATH.write_text("{}", encoding="utf-8")


def _path() -> Path:
    if _PATH is None:
        init(Path("runs"))
    assert _PATH is not None
    return _PATH


def _load() -> Dict[str, Any]:
    try:
        return json.loads(_path().read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}


def _save(data: Dict[str, Any]) -> None:
    p = _path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def extract_api_key(headers: Any) -> str:
    h = headers or {}
    # starlette Headers is case-insensitive
    raw = (h.get("x-lolm-api-key") or h.get("X-LOLM-Api-Key") or "").strip()
    if raw:
        return raw
    auth = (h.get("authorization") or h.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def read_api_key(token: str) -> Optional[Dict[str, Any]]:
    """Validate token → {key_id, tier, label, sub_id} or None."""
    token = (token or "").strip()
    if not token.startswith("lolm_") or token.count("_") < 2:
        return None
    parts = token.split("_", 2)
    if len(parts) != 3:
        return None
    kid = parts[1]
    with _LOCK:
        data = _load()
        row = data.get(kid)
        if not row or row.get("revoked"):
            return None
        want = str(row.get("hash") or "")
        got = _hash(token)
        if len(want) != len(got) or not hmac.compare_digest(want, got):
            return None
        # touch last_used
        row["last_used"] = int(time.time())
        data[kid] = row
        try:
            _save(data)
        except Exception:
            pass
        return {
            "key_id": kid,
            "tier": row.get("tier") or "free",
            "label": row.get("label") or "",
            "sub_id": row.get("sub_id") or "",
        }


def _create_rate_ok(ip: str, max_per_day: int = 5) -> bool:
    now = time.time()
    window = _CREATE_LOG.setdefault(ip or "?", [])
    _CREATE_LOG[ip or "?"] = [t for t in window if now - t < 86400]
    if len(_CREATE_LOG[ip or "?"]) >= max_per_day:
        return False
    _CREATE_LOG[ip or "?"].append(now)
    return True


def mint_api_key(
    *,
    tier: str,
    label: str = "",
    sub_id: str = "",
    ip: str = "",
) -> Dict[str, Any]:
    """Create a key. Returns raw token once + metadata."""
    from local_ui.usage_limits import TIERS
    if tier not in TIERS:
        return {"error": "unknown tier"}
    if not _create_rate_ok(ip):
        return {"error": "key creation rate limit (5/day per IP)"}
    kid = secrets.token_hex(8)
    secret = secrets.token_hex(24)
    raw = f"lolm_{kid}_{secret}"
    now = int(time.time())
    with _LOCK:
        data = _load()
        data[kid] = {
            "tier": tier,
            "hash": _hash(raw),
            "label": (label or "default")[:80],
            "sub_id": (sub_id or "")[:64],
            "created": now,
            "last_used": 0,
            "revoked": False,
        }
        _save(data)
    return {
        "api_key": raw,
        "key_id": kid,
        "tier": tier,
        "label": (label or "default")[:80],
        "created": now,
        "note": "Store this key now — it is not shown again.",
    }


def revoke_api_key(key_id: str, *, owner_sub: str = "", require_sub: bool = False) -> bool:
    with _LOCK:
        data = _load()
        row = data.get(key_id)
        if not row:
            return False
        if require_sub and owner_sub and row.get("sub_id") != owner_sub:
            return False
        row["revoked"] = True
        row["revoked_at"] = int(time.time())
        data[key_id] = row
        _save(data)
        return True


def list_keys_meta(*, sub_id: str = "", include_revoked: bool = False) -> List[Dict[str, Any]]:
    with _LOCK:
        data = _load()
    out = []
    for kid, row in data.items():
        if not include_revoked and row.get("revoked"):
            continue
        if sub_id and row.get("sub_id") != sub_id and row.get("tier") != "free":
            # free keys list only when filtering by empty or matching
            if sub_id:
                continue
        out.append({
            "key_id": kid,
            "tier": row.get("tier"),
            "label": row.get("label"),
            "created": row.get("created"),
            "last_used": row.get("last_used"),
            "revoked": bool(row.get("revoked")),
            "prefix": f"lolm_{kid}_…",
        })
    out.sort(key=lambda r: -int(r.get("created") or 0))
    return out[:50]
