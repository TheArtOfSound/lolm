#!/usr/bin/env bash
# Copyright (c) 2026 Qira LLC. All rights reserved.
# Provision staging-only secrets on the deploy host. Never prints secret values.
#
# Required:
#   DEPLOY_SSH_HOST
# Optional:
#   STAGING_APP_DIR (default /opt/apps/lolm-track2b-staging)
#   ANTHROPIC_API_KEY — if set locally, transferred securely; else host must already have it
set -euo pipefail

HOST="${DEPLOY_SSH_HOST:?set DEPLOY_SSH_HOST}"
APP="${STAGING_APP_DIR:-/opt/apps/lolm-track2b-staging}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
SHA="$(git rev-parse HEAD)"
SHORT="${SHA:0:12}"
KID="track2b-staging-2026-08-${SHORT}"

ssh "$HOST" "sudo mkdir -p '$APP' && sudo chown ubuntu:ubuntu '$APP'"

# Generate secrets ON the host so private material never lands in local shell history.
ssh "$HOST" "python3 - <<'PY'
import secrets, json, os, hashlib, base64
from pathlib import Path
app = Path('${APP}')
app.mkdir(parents=True, exist_ok=True)
env_path = app / '.staging.env'
pub_path = app / '.staging.public.json'
kid = '${KID}'

# Ed25519 via PyNaCl if available, else openssl fallback note
try:
    from nacl.signing import SigningKey
    sk = SigningKey.generate()
    seed_b64 = base64.urlsafe_b64encode(bytes(sk)).decode().rstrip('=')
    pub_b64 = base64.urlsafe_b64encode(bytes(sk.verify_key)).decode().rstrip('=')
    pub_raw = bytes(sk.verify_key)
except Exception:
    # Fallback: 32-byte seed; server receipt_sign accepts hex/b64 seeds
    raw = secrets.token_bytes(32)
    seed_b64 = base64.urlsafe_b64encode(raw).decode().rstrip('=')
    # Without nacl we cannot derive public key here — install pynacl in venv
    pub_b64 = ''
    pub_raw = b''
    print('WARN: PyNaCl missing on host for keygen; install pynacl', flush=True)

api_key = 'lolm_stg_' + secrets.token_urlsafe(32)
pub_fp = hashlib.sha256(pub_raw).hexdigest() if pub_raw else ''

lines = [
    f'LOLM_STAGING_API_KEY={api_key}',
    f'LOLM_RECEIPT_SIGNING_KEYS={kid}:{seed_b64}',
    f'LOLM_RECEIPT_ACTIVE_KID={kid}',
]
# Preserve existing ANTHROPIC / WORKERS if already present on host env file
if env_path.exists():
    prev = env_path.read_text()
    for key in ('ANTHROPIC_API_KEY', 'WORKERS_AI_URL', 'WORKERS_AI_SECRET', 'DEMO_REASONER'):
        for line in prev.splitlines():
            if line.startswith(key + '='):
                lines.append(line)
                break

env_path.write_text('\\n'.join(lines) + '\\n')
os.chmod(env_path, 0o600)

pub = {
    'receipt_key_id': kid,
    'receipt_public_key_b64': pub_b64,
    'receipt_public_key_sha256': pub_fp,
    'staging_api_key_path': str(env_path),
    'note': 'private material only in .staging.env (mode 0600)',
}
pub_path.write_text(json.dumps(pub, indent=2) + '\\n')
os.chmod(pub_path, 0o644)
print(json.dumps({'ok': True, 'kid': kid, 'public_key_sha256': pub_fp, 'has_public': bool(pub_b64)}))
PY"

# Optionally inject Anthropic key from local keyfile without printing it
if [ -f "${HOME}/.lolm/keys.env" ]; then
  ANTHRO_LINE=$(grep -E '^ANTHROPIC_API_KEY=' "${HOME}/.lolm/keys.env" | head -1 || true)
  if [ -n "${ANTHRO_LINE}" ]; then
    # Transfer via ssh stdin; do not echo value
    printf '%s\n' "$ANTHRO_LINE" | ssh "$HOST" "grep -v '^ANTHROPIC_API_KEY=' '${APP}/.staging.env' > '${APP}/.staging.env.tmp' || true; cat >> '${APP}/.staging.env.tmp'; mv '${APP}/.staging.env.tmp' '${APP}/.staging.env'; chmod 600 '${APP}/.staging.env'"
    echo "[provision] ANTHROPIC_API_KEY synchronized to staging env (value not logged)"
  fi
fi

# Fetch public material only to local evidence dir
mkdir -p /tmp/track2b-evidence
ssh "$HOST" "cat '${APP}/.staging.public.json'" > /tmp/track2b-evidence/receipt_public.json
# Fetch staging API key into runner secret file (local 0600), never commit
ssh "$HOST" "grep '^LOLM_STAGING_API_KEY=' '${APP}/.staging.env' | cut -d= -f2-" > /tmp/track2b-evidence/staging_api_key.txt
chmod 600 /tmp/track2b-evidence/staging_api_key.txt /tmp/track2b-evidence/receipt_public.json 2>/dev/null || true

echo "[provision] public material → /tmp/track2b-evidence/receipt_public.json"
python3 - <<'PY'
import json
from pathlib import Path
p=Path('/tmp/track2b-evidence/receipt_public.json')
d=json.loads(p.read_text())
print(json.dumps({k:d.get(k) for k in ('receipt_key_id','receipt_public_key_sha256','has_public') if k in d or True}, indent=2))
print('kid:', d.get('receipt_key_id'))
print('pub_fp:', d.get('receipt_public_key_sha256'))
print('pub_len:', len(d.get('receipt_public_key_b64') or ''))
PY
