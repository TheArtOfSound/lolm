#!/usr/bin/env bash
# Install the LOLM evolution daemon as a macOS launchd agent → it runs continuously,
# survives logout/reboot (while the Mac is awake), and auto-restarts if it dies.
#
#   scripts/install_evolve_agent.sh           # install + start
#   launchctl unload ~/Library/LaunchAgents/com.qira.lolm-evolve.plist   # stop
#
# Keep the Mac awake so it evolves overnight / for a week:
#   caffeinate -dimsu -t 604800 &     # stay awake 7 days
# or System Settings → Battery/Energy → "Prevent sleep when display is off".
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
LABEL="com.qira.lolm-evolve"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$REPO/runs/evolve/daemon.log"
mkdir -p "$REPO/runs/evolve" "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string><string>-m</string><string>scripts.evolve_daemon</string>
    <string>--interval</string><string>900</string>
    <string>--device</string><string>mps</string>
    <string>--real-log</string><string>$REPO/local_ui/data/improvement_log.jsonl</string>
    <string>--live-ckpt</string><string>$REPO/runs/nfet_controller/bootstrap_qwen06b.pt</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
  <key>ProcessType</key><string>Background</string>
  <key>Nice</key><integer>10</integer>
</dict></plist>
PLIST

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "installed + started: $LABEL"
echo "  log:    $LOG"
echo "  state:  $REPO/runs/evolve/state.json"
echo "  stop:   launchctl unload $PLIST"
echo "It now evolves every 15 min while this Mac is awake — leave it running for days."
