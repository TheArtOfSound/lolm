#!/usr/bin/env bash
# Copyright (c) 2026 Qira LLC. All rights reserved.
# Deploy the LOLM docs site and retired-API boundary, then prove both surfaces.
# Exits non-zero on any failed check and restores the paired app/web snapshot.
#
# Required env:
#   DEPLOY_SSH_HOST   ssh target (e.g. autohustle-aws)
# Optional env:
#   DEPLOY_APP_DIR    default /opt/apps/lolm
#   DEPLOY_WEB_DIR    default /var/www/lolm-imagineqira
#   DEPLOY_SERVICE    default lolm-demo
#   PUBLIC_BASE       default https://lolm.imagineqira.com
set -euo pipefail

HOST="${DEPLOY_SSH_HOST:?set DEPLOY_SSH_HOST to deploy}"
APP="${DEPLOY_APP_DIR:-/opt/apps/lolm}"
WEB="${DEPLOY_WEB_DIR:-/var/www/lolm-imagineqira}"
SVC="${DEPLOY_SERVICE:-lolm-demo}"
BASE="${PUBLIC_BASE:-https://lolm.imagineqira.com}"
SNAPSHOT_MARKER="${APP}.rollback-snapshot"
ROLLBACK_ARMED=0
cd "$(dirname "$0")/.."

rollback_on_error() {
  rc=$?
  trap - ERR
  set +e
  if [ "$ROLLBACK_ARMED" -eq 1 ]; then
    echo "[deploy] failure after snapshot; restoring paired app + website"
    DEPLOY_SSH_HOST="$HOST" \
    DEPLOY_APP_DIR="$APP" \
    DEPLOY_WEB_DIR="$WEB" \
    DEPLOY_SERVICE="$SVC" \
      bash deploy/rollback_box.sh
    rollback_rc=$?
    if [ "$rollback_rc" -ne 0 ]; then
      echo "[deploy] CRITICAL: automatic rollback failed with exit $rollback_rc"
    fi
  else
    echo "[deploy] failure occurred before a new rollback snapshot was armed"
  fi
  exit "$rc"
}
trap rollback_on_error ERR

echo "[deploy] snapshotting current app + website for rollback (keeps newest 3)"
ssh "$HOST" "
  set -e
  TS=\$(date +%Y%m%d%H%M%S)
  sudo rsync -a --exclude .venv --exclude runs --exclude __pycache__ '$APP/' \"${APP}.bak.\$TS/\"
  sudo rsync -a '$WEB/' \"${WEB}.bak.\$TS/\"
  printf '%s\n' \"\$TS\" | sudo tee '$SNAPSHOT_MARKER' >/dev/null
  echo '[deploy] snapshot id → '\$TS
  echo '[deploy] app backup → ${APP}.bak.'\$TS
  echo '[deploy] web backup → ${WEB}.bak.'\$TS
  ls -dt ${APP}.bak.* 2>/dev/null | tail -n +4 | xargs -r sudo rm -rf
  ls -dt ${WEB}.bak.* 2>/dev/null | tail -n +4 | xargs -r sudo rm -rf
"
ROLLBACK_ARMED=1

echo "[deploy] syncing code → $HOST:$APP (checksum; box is not a git repo)"
rsync -rc --delete --exclude '.venv' --exclude '__pycache__' --exclude 'runs' \
  lolm/ "$HOST:$APP/lolm/"
rsync -rc --exclude '__pycache__' local_ui/ "$HOST:$APP/local_ui/"
rsync -rc scripts/ "$HOST:$APP/scripts/"
# Root runtime hooks are not contained in lolm/ or local_ui/. Keep this explicit
# so a production fix cannot pass CI and then disappear during rsync.
rsync -rc sitecustomize.py "$HOST:$APP/sitecustomize.py"

echo "[deploy] syncing static site → $HOST:$WEB"
rsync -rc --delete --rsync-path="sudo rsync" site/ "$HOST:$WEB/"

echo "[deploy] pinning application root into the service venv"
ssh "$HOST" "set -e; SITE=\$('$APP/.venv/bin/python' -c 'import site; print(site.getsitepackages()[0])'); printf '%s\n' '$APP' > \"\$SITE/lolm_app_root.pth\""

echo "[deploy] validating the docs-only product contract on the box"
ssh "$HOST" "cd '$APP' && '$APP/.venv/bin/python' -m py_compile local_ui/server_public_demo.py && python3 - '$WEB/product-config.json' <<'PY'
import json
import sys

with open(sys.argv[1], encoding='utf-8') as handle:
    config = json.load(handle)
assert config['product']['mode'] == 'open_source_cli'
assert config['execution'] == {'website': False, 'cli': True, 'hosted_api': False}
assert config['commercial_license']['available'] is True
assert config['commercial_license']['public_prices'] is False
print('docs-only product contract OK')
PY"

echo "[deploy] clearing stale bytecode + restarting $SVC"
ssh "$HOST" "find $APP -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null; sudo systemctl restart $SVC; sleep 3; systemctl is-active $SVC"

# The compatibility service still imports the legacy runtime before binding.
# Poll its inert health endpoint without reviving a model-execution route.
echo "[deploy] waiting for the docs boundary to become ready (up to 90s)"
ready=0
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE/api/demo/health" || echo 000)
  if [ "$code" = "200" ]; then ready=1; echo "[deploy] app ready after ~$((i*3))s"; break; fi
  sleep 3
done
if [ "$ready" -ne 1 ]; then echo "[deploy] app never became ready — failing"; exit 1; fi

fail=0
check() { # name url expect
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$2" || echo 000)
  if [ "$code" = "$3" ]; then echo "[smoke] OK   $1 ($code) $2"; else echo "[smoke] FAIL $1 ($code != $3) $2"; fail=1; fi
}
echo "[deploy] smoke + health + critical routes"
check "homepage"       "$BASE/"                         200
check "install docs"   "$BASE/install.html"             200
check "CLI docs"       "$BASE/docs.html"                200
check "static contract" "$BASE/product-config.json"     200
check "health"         "$BASE/api/demo/health"          200
check "API contract"   "$BASE/api/demo/product-config"  200
check "old status retired" "$BASE/api/demo/status"      410

run_code=$(curl -s -o /tmp/lolm-retired-run.json -w '%{http_code}' --max-time 20 \
  -H 'content-type: application/json' -d '{"prompt":"should not run"}' \
  "$BASE/api/demo/run/stream" || echo 000)
if [ "$run_code" = "410" ]; then
  echo "[smoke] OK   hosted execution retired ($run_code) $BASE/api/demo/run/stream"
else
  echo "[smoke] FAIL hosted execution retired ($run_code != 410) $BASE/api/demo/run/stream"
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  echo "[deploy] FAILED health/smoke"
  exit 1
fi

product_tmp=$(mktemp)
curl -fsS --max-time 20 "$BASE/api/demo/product-config" > "$product_tmp"
python3 - "$product_tmp" <<'PY'
import json
import sys

with open(sys.argv[1], encoding='utf-8') as handle:
    config = json.load(handle)
assert config['execution'] == {'website': False, 'cli': True, 'hosted_api': False}
assert config['commercial_license']['available'] is True
assert 'plans' not in config and 'billing' not in config
print('[smoke] OK   live API advertises local CLI without public pricing')
PY
rm -f "$product_tmp" /tmp/lolm-retired-run.json

ROLLBACK_ARMED=0
trap - ERR
echo "[deploy] live at $BASE — docs, install path, and retired execution boundary green"
