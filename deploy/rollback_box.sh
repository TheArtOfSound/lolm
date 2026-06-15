#!/usr/bin/env bash
# Copyright (c) 2026 Qira LLC. All rights reserved.
# Roll production back to the last-known-good code and restart, then re-check health.
# The box keeps a timestamped backup of the app dir on every deploy; this restores it.
#
# Required env: DEPLOY_SSH_HOST
set -euo pipefail

HOST="${DEPLOY_SSH_HOST:?set DEPLOY_SSH_HOST to roll back}"
APP="${DEPLOY_APP_DIR:-/opt/apps/lolm}"
SVC="${DEPLOY_SERVICE:-lolm-demo}"
BASE="${PUBLIC_BASE:-https://lolm.imagineqira.com}"

echo "[rollback] restoring last-known-good on $HOST and restarting $SVC"
ssh "$HOST" "
  set -e
  PREV=\$(ls -dt ${APP}.bak.* 2>/dev/null | head -1 || true)
  if [ -n \"\$PREV\" ]; then
    echo '[rollback] restoring '\$PREV
    sudo rsync -rc --delete --exclude runs --exclude .venv \"\$PREV/\" '$APP/'
  else
    echo '[rollback] no backup snapshot found — restarting current build'
  fi
  find $APP -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
  sudo systemctl restart $SVC
  sleep 5
  systemctl is-active $SVC
"
# Same readiness poll as deploy — the app needs ~10-15s to bind after restart.
code=000
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE/api/demo/status" || echo 000)
  [ "$code" = "200" ] && break
  sleep 3
done
echo "[rollback] health after rollback: $code"
[ "$code" = "200" ] || { echo "[rollback] STILL UNHEALTHY — page a human"; exit 1; }
echo "[rollback] healthy at $BASE"
