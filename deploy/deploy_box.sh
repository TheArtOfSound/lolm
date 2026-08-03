#!/usr/bin/env bash
# Copyright (c) 2026 Qira LLC. All rights reserved.
# Deploy LOLM to the production box, then prove it with smoke + health checks.
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

echo "[deploy] proving runtime imports and artifact/task-state/contract patches"
ssh "$HOST" "cd / && '$APP/.venv/bin/python' - <<'PY'
from lolm.control.task_state import (
    allow_finalize_from_state,
    load_or_init,
    observe_workspace_artifacts,
    policy_action,
    update_task_state,
)
from lolm.reliability.contract_compiler import compile_contract
from local_ui.code_agent import CodeAgent
assert getattr(CodeAgent, '_artifact_delivery_patch', False), 'artifact delivery patch not active'
assert getattr(CodeAgent, '_credential_safety_patch', False), 'credential safety patch not active'
assert getattr(CodeAgent, '_task_state_artifact_patch', False), 'task-state artifact bridge not active'
contract = compile_contract(
    'Create main.py that generates output.pdf visibly labeled '
    'UNOFFICIAL LOLM P0 CLOSURE BROWSER TEST'
)
assert contract.primary_language == 'pdf'
assert not any(
    c.hardness == 'hard' and c.verifier == 'html.render'
    for c in contract.clauses
), 'non-HTML task gained an html.render requirement'
st = load_or_init('create output.pdf', session='deploy-self-test', resume=False)
st = update_task_state(
    st,
    observation='PDF_READY output.pdf',
    action='run',
    result={'files': ['main.py'], 'exit_ok': True, 'produced_output': True},
)
assert allow_finalize_from_state(st) is False
observe_workspace_artifacts(st, ['main.py', 'output.pdf'])
assert allow_finalize_from_state(st) is True
assert policy_action(st)['block_finalize'] is False
print('runtime patches + generated-artifact task state + contract medium OK')
PY"

echo "[deploy] clearing stale bytecode + restarting $SVC"
ssh "$HOST" "find $APP -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null; sudo systemctl restart $SVC; sleep 3; systemctl is-active $SVC"

# The app imports torch + loads the model on boot, so it binds in ~10-15s. Poll
# for readiness instead of checking once too early.
echo "[deploy] waiting for the app to become ready (up to 90s)"
ready=0
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE/api/demo/status" || echo 000)
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
check "health"        "$BASE/api/demo/status"          200
check "lolm_demo"     "$BASE/"                          200
check "artifact_ui"   "$BASE/artifact-delivery-ui.js"  200
check "receipt_route" "$BASE/api/demo/hf/dashboard"     200
check "research"      "$BASE/api/demo/research/jobs"    200

if [ "$fail" -ne 0 ]; then
  echo "[deploy] FAILED health/smoke"
  exit 1
fi

echo "[deploy] running real CodeAgent PDF delivery smoke"
python3 scripts/smoke_pdf_delivery.py --base "$BASE" --attempts 3 --timeout 600

ROLLBACK_ARMED=0
trap - ERR
echo "[deploy] live at $BASE — all checks and exact-byte PDF delivery green"
