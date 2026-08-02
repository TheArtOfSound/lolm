#!/usr/bin/env bash
# Copyright (c) 2026 Qira LLC. All rights reserved.
# Deploy SHA-pinned Track 2B staging to the existing box (separate from production).
#
# Required env:
#   DEPLOY_SSH_HOST   e.g. autohustle-aws or ubuntu@host
# Optional:
#   STAGING_APP_DIR   default /opt/apps/lolm-track2b-staging
#   STAGING_PORT      default 7870
#   STAGING_SERVICE   default lolm-track2b-staging
set -euo pipefail

HOST="${DEPLOY_SSH_HOST:?set DEPLOY_SSH_HOST}"
APP="${STAGING_APP_DIR:-/opt/apps/lolm-track2b-staging}"
PORT="${STAGING_PORT:-7870}"
SVC="${STAGING_SERVICE:-lolm-track2b-staging}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

SHA="$(git rev-parse HEAD)"
SHORT="${SHA:0:12}"
DEPLOY_ID="track2b-staging-${SHORT}-$(date -u +%Y%m%dT%H%M%SZ)"
BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "[track2b-staging] SHA=$SHA"
echo "[track2b-staging] DEPLOY_ID=$DEPLOY_ID"
echo "[track2b-staging] target $HOST:$APP port=$PORT"

ssh "$HOST" "sudo mkdir -p '$APP' '$APP/runs/code_sandboxes' '$APP/runs/usage' && sudo chown -R ubuntu:ubuntu '$APP'"

echo "[track2b-staging] rsync code"
rsync -rc --delete \
  --exclude '.venv' --exclude '__pycache__' --exclude 'runs' --exclude '.git' \
  --exclude 'node_modules' --exclude 'site' \
  lolm/ "$HOST:$APP/lolm/"
rsync -rc --exclude '__pycache__' local_ui/ "$HOST:$APP/local_ui/"
rsync -rc scripts/ "$HOST:$APP/scripts/"
# share production venv if present (torch already installed) — symlink
ssh "$HOST" "if [ ! -e '$APP/.venv' ] && [ -x /opt/apps/lolm/.venv/bin/python ]; then ln -sfn /opt/apps/lolm/.venv '$APP/.venv'; fi"
ssh "$HOST" "test -x '$APP/.venv/bin/python' || { echo 'missing venv at $APP/.venv — create one'; exit 1; }"

# Write unit file
ssh "$HOST" "sudo tee /etc/systemd/system/${SVC}.service >/dev/null" <<EOF
[Unit]
Description=LOLM Track 2B SHA-pinned staging (not production)
After=network.target

[Service]
EnvironmentFile=-${APP}/.staging.env
Type=simple
User=ubuntu
WorkingDirectory=${APP}
Environment=PYTHONPATH=.
Environment=HOST=127.0.0.1
Environment=PORT=${PORT}
Environment=OMP_NUM_THREADS=2
Environment=MKL_NUM_THREADS=2
Environment=DEMO_PROFILE=qwen3_0_6b_smoke
Environment=DEMO_DEVICE=cpu
Environment=DEMO_GRAFT_CKPT=/opt/apps/lolm/runs/nfet_controller/live_qwen06b.pt
Environment=LOCAL_UI_DATA_DIR=${APP}/local_ui/data
Environment=LOLM_SERVER_SHA=${SHA}
Environment=LOLM_DEPLOYMENT_ID=${DEPLOY_ID}
Environment=LOLM_ENVIRONMENT=track2b-staging
Environment=LOLM_BUILD_TIME=${BUILD_TIME}
Environment=LOLM_MODEL_ID=${STAGING_MODEL_ID:-llama-3.3-70b-versatile}
Environment=LOLM_MODEL_PROVIDER=${STAGING_MODEL_PROVIDER:-groq}
Environment=LOLM_BRAIN=${STAGING_BRAIN:-cloud}
Environment=DEMO_REASONER=${STAGING_BRAIN:-cloud}
Environment=GROQ_MODEL=${STAGING_MODEL_ID:-llama-3.3-70b-versatile}
Environment=LOLM_STAGING_RATE_PER_MIN=${STAGING_RATE_PER_MIN:-120}
Environment=LOLM_TRACK2B_STRICT_CHAT=1
ExecStart=${APP}/.venv/bin/python local_ui/server_public_demo.py
Restart=on-failure
RestartSec=5
Nice=10
MemoryMax=4G
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

# Ensure staging env exists (secrets provisioned separately)
ssh "$HOST" "test -f '$APP/.staging.env' || { echo 'missing $APP/.staging.env — run provision_secrets.sh first'; exit 1; }"

# Provider deps: anthropic optional; always ensure present for Claude path.
# Staging shares /opt/apps/lolm/.venv (uv-managed) — install via uv, not pip.
ssh "$HOST" 'export PATH="$HOME/.local/bin:$PATH"
  if command -v uv >/dev/null; then
    uv pip install --python /opt/apps/lolm/.venv/bin/python "anthropic>=0.40.0" >/tmp/track2b-uv-anthropic.log 2>&1 || true
  fi
  /opt/apps/lolm/.venv/bin/python -c "import anthropic; print(anthropic.__version__)" 2>/dev/null || echo "anthropic not installed (ok if using groq/direct)"
'

# Sync approved provider keys from production demo env into staging secrets
# without printing values. Prefer GROQ (validated working) over invalid Anthropic.
ssh "$HOST" "python3 - <<'PY'
from pathlib import Path
demo = Path('/opt/apps/lolm/.demo.env')
stg = Path('${APP}/.staging.env')
if not demo.is_file() or not stg.is_file():
    raise SystemExit(0)
def parse(p):
    out = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        out[k.strip()] = v.strip().strip('\"').strip(\"'\")
    return out
d, s = parse(demo), parse(stg)
# Copy only known provider credential names if staging lacks a working set
for k in ('GROQ_API_KEY', 'OPENROUTER_API_KEY', 'GEMINI_API_KEY'):
    if d.get(k) and not s.get(k):
        s[k] = d[k]
# Track 2B fixed-model campaign currently pins groq — do not force broken Anthropic.
# Keep ANTHROPIC only if already present; operator may rotate later.
# Ensure rate/brain identity helpers are non-secret defaults in env file when missing.
s.setdefault('LOLM_STAGING_RATE_PER_MIN', '${STAGING_RATE_PER_MIN:-120}')
# Drop empty keys
lines = [f'{k}={v}' for k, v in sorted(s.items()) if v]
stg.write_text('\\n'.join(lines) + '\\n')
print('staging.env provider keys synced (names only):',
      sorted(k for k in s if k.endswith('_KEY') or k.endswith('_SECRET')))
PY"

ssh "$HOST" "sudo systemctl daemon-reload && sudo systemctl enable '${SVC}' && sudo systemctl restart '${SVC}'"

# Nginx location for /api/track2b/ → staging backend /api/demo/
ssh "$HOST" "sudo tee /etc/nginx/snippets/lolm-track2b-staging.conf >/dev/null" <<'NGX'
# Track 2B staging — path-prefixed product route (not production 7866)
location /api/track2b/ {
    proxy_pass http://127.0.0.1:7870/api/demo/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    proxy_connect_timeout 4s;
}
NGX

# Include snippet in lolm vhost if not already present
ssh "$HOST" '
  conf=/etc/nginx/sites-enabled/lolm.imagineqira.com
  if ! sudo grep -q lolm-track2b-staging.conf "$conf" 2>/dev/null; then
    sudo cp "$conf" "${conf}.bak.track2b"
    # Insert include after server_name line
    sudo python3 - <<PY
from pathlib import Path
p = Path("/etc/nginx/sites-enabled/lolm.imagineqira.com")
t = p.read_text()
needle = "include snippets/ga.conf;"
inc = "include snippets/ga.conf;\n    include snippets/lolm-track2b-staging.conf;"
if "lolm-track2b-staging.conf" not in t:
    if needle in t:
        t = t.replace(needle, inc, 1)
    else:
        t = t.replace("server_name lolm.imagineqira.com;", "server_name lolm.imagineqira.com;\n    include snippets/lolm-track2b-staging.conf;", 1)
    p.write_text(t)
    print("nginx snippet wired")
else:
    print("nginx snippet already present")
PY
    sudo nginx -t && sudo systemctl reload nginx
  else
    echo "nginx already includes track2b snippet"
    sudo nginx -t && sudo systemctl reload nginx || true
  fi
'

echo "[track2b-staging] waiting for readiness"
ready=0
for i in $(seq 1 40); do
  code=$(ssh "$HOST" "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:${PORT}/api/demo/status" || echo 000)
  if [ "$code" = "200" ]; then ready=1; echo "[track2b-staging] ready after ~$((i*3))s"; break; fi
  sleep 3
done
if [ "$ready" -ne 1 ]; then
  echo "[track2b-staging] FAILED to become ready"
  ssh "$HOST" "sudo journalctl -u ${SVC} -n 40 --no-pager" || true
  exit 1
fi

# Emit non-secret identity for the runner
ssh "$HOST" "curl -s http://127.0.0.1:${PORT}/api/demo/status" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(json.dumps({k:d.get(k) for k in ("server_sha","deployment_id","isolation","bwrap","environment","model_id","provider","adaptive_routing","model_ready")}, indent=2))'

# Write local freeze record (no secrets)
mkdir -p /tmp/track2b-evidence
cat > /tmp/track2b-evidence/deployment.json <<JSON
{
  "server_sha": "${SHA}",
  "deployment_id": "${DEPLOY_ID}",
  "build_time": "${BUILD_TIME}",
  "public_base": "https://lolm.imagineqira.com",
  "api_prefix": "/api/track2b",
  "code_run_path": "/api/track2b/code/run",
  "status_path": "/api/track2b/status",
  "host": "${HOST}",
  "port": ${PORT},
  "service": "${SVC}"
}
JSON
echo "[track2b-staging] deployment record → /tmp/track2b-evidence/deployment.json"
echo "[track2b-staging] live path https://lolm.imagineqira.com/api/track2b/status"
