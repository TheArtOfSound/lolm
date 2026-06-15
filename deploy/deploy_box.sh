#!/usr/bin/env bash
# Copyright (c) 2026 Qira LLC. All rights reserved.
# Deploy LOLM to the production box, then prove it with smoke + health checks.
# Exits non-zero on any failed check so the daily agent's DeployGate blocks + rolls back.
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
cd "$(dirname "$0")/.."

echo "[deploy] snapshotting current build for rollback (keeps newest 3)"
ssh "$HOST" "TS=\$(date +%Y%m%d%H%M%S); \
  sudo rsync -a --exclude .venv --exclude runs --exclude __pycache__ '$APP/' \"${APP}.bak.\$TS/\" && \
  echo '[deploy] backup → ${APP}.bak.'\$TS; \
  ls -dt ${APP}.bak.* 2>/dev/null | tail -n +4 | xargs -r sudo rm -rf"

echo "[deploy] syncing code → $HOST:$APP (checksum; box is not a git repo)"
rsync -rc --delete --exclude '.venv' --exclude '__pycache__' --exclude 'runs' \
  lolm/ "$HOST:$APP/lolm/"
rsync -rc --exclude '__pycache__' local_ui/ "$HOST:$APP/local_ui/"
rsync -rc scripts/ "$HOST:$APP/scripts/"

echo "[deploy] syncing static site → $HOST:$WEB"
rsync -rc --rsync-path="sudo rsync" site/ "$HOST:$WEB/"

echo "[deploy] clearing stale bytecode + restarting $SVC"
ssh "$HOST" "find $APP -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null; sudo systemctl restart $SVC; sleep 3; systemctl is-active $SVC"

# The app imports torch + loads the model on boot, so it binds in ~10-15s. Poll
# for readiness instead of checking once too early (that produced false 502s).
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
check "receipt_route" "$BASE/api/demo/hf/dashboard"     200
check "research"      "$BASE/api/demo/research/jobs"    200

if [ "$fail" -ne 0 ]; then
  echo "[deploy] FAILED health/smoke — see DeployGate; run deploy/rollback_box.sh"
  exit 1
fi
echo "[deploy] live at $BASE — all checks green"
