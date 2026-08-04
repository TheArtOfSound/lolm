#!/usr/bin/env bash
# Install the LOLM product evolution plane + evolved serve as launchd agents.
#
#   bash scripts/install_evolution_agent.sh
#   bash scripts/install_evolution_agent.sh --uninstall
#
# Agents:
#   com.qira.lolm-evolved-serve  — serve LOLM-Core (evolution live + canary)
#   com.qira.lolm-evolution      — harvest/train/eval/promote cycle on interval
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
LA="$HOME/Library/LaunchAgents"
mkdir -p "$LA" "$HOME/.lolm" "$REPO/runs/evolution"

uninstall() {
  for label in com.qira.lolm-evolved-serve com.qira.lolm-evolution; do
    launchctl unload "$LA/$label.plist" 2>/dev/null || true
    rm -f "$LA/$label.plist"
  done
  echo "✓ evolution agents removed"
}

if [ "${1:-}" = "--uninstall" ]; then
  uninstall
  exit 0
fi

# stop prior
for label in com.qira.lolm-evolved-serve com.qira.lolm-evolution com.qira.lolm-knowledge; do
  launchctl unload "$LA/$label.plist" 2>/dev/null || true
done

# Serve
cat > "$LA/com.qira.lolm-evolved-serve.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.qira.lolm-evolved-serve</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$REPO/scripts/serve_evolved.py</string>
    <string>--port</string><string>11435</string>
    <string>--repo</string><string>$REPO</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key><string>$REPO</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/.lolm/com.qira.lolm-evolved-serve.log</string>
  <key>StandardErrorPath</key><string>$HOME/.lolm/com.qira.lolm-evolved-serve.log</string>
</dict></plist>
PL

# Evolution daemon — interval 30m, bootstrap force until Gold mass grows
cat > "$LA/com.qira.lolm-evolution.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.qira.lolm-evolution</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$REPO/scripts/evolution_daemon.py</string>
    <string>--interval</string><string>1800</string>
    <string>--force</string>
    <string>--canary</string><string>0.05</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key><string>$REPO</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/.lolm/com.qira.lolm-evolution.log</string>
  <key>StandardErrorPath</key><string>$HOME/.lolm/com.qira.lolm-evolution.log</string>
  <key>Nice</key><integer>10</integer>
</dict></plist>
PL

launchctl load "$LA/com.qira.lolm-evolved-serve.plist"
launchctl load "$LA/com.qira.lolm-evolution.plist"
sleep 2
echo "✓ Installed LOLM evolution plane agents:"
launchctl list | grep -E "lolm-evolved-serve|lolm-evolution" || true
echo "  serve  → http://127.0.0.1:11435"
echo "  logs   → ~/.lolm/"
echo "  brain  → LOLM_LOCAL_API=openai LOLM_LOCAL_URL=http://127.0.0.1:11435 LOLM_LOCAL_MODEL=lolm-evolved"
echo "  stop   → bash scripts/install_evolution_agent.sh --uninstall"
