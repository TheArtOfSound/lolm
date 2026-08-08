#!/usr/bin/env bash
# Copyright (c) 2026 Qira LLC. All rights reserved.
# Roll production back to the explicitly paired last-known-good application and
# static website snapshot, restart the service, then re-check health.
#
# Required env: DEPLOY_SSH_HOST
set -euo pipefail

HOST="${DEPLOY_SSH_HOST:?set DEPLOY_SSH_HOST to roll back}"
APP="${DEPLOY_APP_DIR:-/opt/apps/lolm}"
WEB="${DEPLOY_WEB_DIR:-/var/www/lolm-imagineqira}"
SVC="${DEPLOY_SERVICE:-lolm-demo}"
BASE="${PUBLIC_BASE:-https://lolm.imagineqira.com}"
SNAPSHOT_MARKER="${APP}.rollback-snapshot"

echo "[rollback] restoring paired last-known-good app + website on $HOST"
ssh "$HOST" "
  set -e
  if [ ! -s '$SNAPSHOT_MARKER' ]; then
    echo '[rollback] snapshot marker missing — refusing an unbound rollback'
    exit 1
  fi
  TS=\$(sudo cat '$SNAPSHOT_MARKER' | tr -cd '0-9')
  PREV_APP='${APP}.bak.'\$TS
  PREV_WEB='${WEB}.bak.'\$TS
  if [ -z \"\$TS\" ] || [ ! -d \"\$PREV_APP\" ] || [ ! -d \"\$PREV_WEB\" ]; then
    echo '[rollback] paired app/web snapshot missing — refusing partial rollback'
    exit 1
  fi
  echo '[rollback] snapshot id '\$TS
  echo '[rollback] restoring app '\$PREV_APP
  sudo rsync -rc --delete --exclude runs --exclude .venv \"\$PREV_APP/\" '$APP/'
  echo '[rollback] restoring website '\$PREV_WEB
  sudo rsync -rc --delete \"\$PREV_WEB/\" '$WEB/'
  find '$APP' -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
  sudo systemctl restart '$SVC'
  sleep 5
  systemctl is-active '$SVC'
"

# Same readiness poll as deploy — product config is valid on both the prior and
# current public architectures and does not execute a model.
code=000
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE/api/demo/product-config" || echo 000)
  [ "$code" = "200" ] && break
  sleep 3
done
echo "[rollback] health after rollback: $code"
[ "$code" = "200" ] || { echo "[rollback] STILL UNHEALTHY — page a human"; exit 1; }

web_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE/" || echo 000)
echo "[rollback] website after rollback: $web_code"
[ "$web_code" = "200" ] || { echo "[rollback] WEBSITE STILL UNHEALTHY — page a human"; exit 1; }
echo "[rollback] app + website healthy at $BASE"
