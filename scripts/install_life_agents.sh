#!/bin/bash
# Copyright (c) 2026 Qira LLC. All rights reserved.
#
# Install LOLM's "always alive" launchd agents on your Mac — the half of the loop that
# lives on your machine. Two agents, both KeepAlive (survive logout/crash, restart on wake):
#
#   com.qira.lolm-evolved-serve  — always serves LOLM's SELF-LEARNED weights on :11435
#   com.qira.lolm-knowledge      — every 30min: PULL the facts LOLM thought up on the box
#                                   (/api/demo/life/facts) → train them in, GATED → on a
#                                   promotion, restart the serve so the new weights go live.
#
# Together with the box's life cron (thinks 24/7, mints facts), this is the full circle:
# a thought at 3am on the server becomes trained, served weights on your Mac by morning.
#
#   bash scripts/install_life_agents.sh              # install + start
#   bash scripts/install_life_agents.sh --uninstall  # stop + remove
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
LA="$HOME/Library/LaunchAgents"
PULL="${LOLM_PULL_URL:-https://lolm.imagineqira.com/api/demo/life/facts}"
mkdir -p "$LA" "$HOME/.lolm"

plist () {  # label, python-args...
  local label="$1"; shift
  local args=""; for a in "$@"; do args+="    <string>$a</string>
"; done
  cat > "$LA/$label.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array>
    <string>$PY</string>
$args  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key><dict><key>PYTHONPATH</key><string>$REPO</string></dict>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/.lolm/$label.log</string>
  <key>StandardErrorPath</key><string>$HOME/.lolm/$label.log</string>
</dict></plist>
PL
}

for label in com.qira.lolm-evolved-serve com.qira.lolm-knowledge com.qira.lolm-evolution; do
  launchctl unload "$LA/$label.plist" 2>/dev/null || true
done

if [ "$1" = "--uninstall" ]; then
  rm -f "$LA/com.qira.lolm-evolved-serve.plist" "$LA/com.qira.lolm-knowledge.plist" \
        "$LA/com.qira.lolm-evolution.plist"
  echo "✓ LOLM life agents removed."
  exit 0
fi

plist com.qira.lolm-evolved-serve scripts/serve_evolved.py --port 11435 --repo "$REPO"
# Product evolution plane (skills from verified trajectories) — primary learning path
plist com.qira.lolm-evolution scripts/evolution_daemon.py \
      --interval 1800 --force --canary 0.05
# Optional fact LoRA still available but volatile pricing filtered in train_improve_loop
plist com.qira.lolm-knowledge scripts/evolve_knowledge_daemon.py \
      --interval 3600 --batch 4 --pull-url "$PULL"

launchctl load "$LA/com.qira.lolm-evolved-serve.plist"
launchctl load "$LA/com.qira.lolm-evolution.plist"
launchctl load "$LA/com.qira.lolm-knowledge.plist"
sleep 3
echo "✓ Installed. LOLM now learns while you sleep:"
launchctl list | grep -E "lolm-evolved-serve|lolm-evolution|lolm-knowledge" | awk '{print "   "$3" (pid "$1")"}'
echo "   evolved weights served → http://127.0.0.1:11435 · logs → ~/.lolm/"
echo "   evolution plane + canary promote · retrieval facts for pricing/URLs"
echo "   point the sovereign brain at them: LOLM_LOCAL_API=openai LOLM_LOCAL_URL=http://127.0.0.1:11435 LOLM_LOCAL_MODEL=lolm-evolved"
