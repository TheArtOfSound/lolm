#!/usr/bin/env bash
# Push the bench copy to the box. A SEPARATE dir from /opt/apps/lolm so measuring
# and iterating never touches the live service; it shares the prod venv read-only.
set -euo pipefail
HOST="${DEPLOY_SSH_HOST:-autohustle-aws}"
DIR="${BENCH_DIR:-/opt/apps/lolm-bench}"
cd "$(dirname "$0")/.."
ssh "$HOST" "mkdir -p $DIR/runs && [ -e $DIR/.venv ] || ln -s /opt/apps/lolm/.venv $DIR/.venv"
rsync -rc --exclude '__pycache__' lolm/      "$HOST:$DIR/lolm/"
rsync -rc --exclude '__pycache__' local_ui/  "$HOST:$DIR/local_ui/"
rsync -rc --exclude '__pycache__' scripts/   "$HOST:$DIR/scripts/"
rsync -rc --exclude '__pycache__' --exclude 'results' bench/ "$HOST:$DIR/bench/"
ssh "$HOST" "find $DIR -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null; true"
echo "[sync] $DIR updated on $HOST"
