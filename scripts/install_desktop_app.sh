#!/bin/bash
# Copyright (c) 2026 Qira LLC. All rights reserved.
#
# Install a double-clickable LOLM.app on your Desktop. One click starts your local
# sovereign LOLM (operator in owner-local mode, your BYOK keys loaded) and opens it in
# the browser. Re-run anytime to refresh.
#
#   bash scripts/install_desktop_app.sh            # -> ~/Desktop/LOLM.app
#   APP_DIR="$HOME/Applications" bash scripts/install_desktop_app.sh
set -e

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || PY="python3"
APP="${APP_DIR:-$HOME/Desktop}/LOLM.app"
PORT="${LOLM_PORT:-7866}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "→ building icon (nested-field mark)…"
"$PY" - "$TMP/master.png" <<'PYEOF'
import sys
from PIL import Image, ImageDraw
S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([0, 0, S - 1, S - 1], radius=228, fill=(244, 63, 94, 255))   # rose
c = S // 2
for r, w in [(372, 42), (258, 38), (150, 34)]:                                    # nested rings
    d.ellipse([c - r, c - r, c + r, c + r], outline=(255, 255, 255, 255), width=w)
d.ellipse([c - 48, c - 48, c + 48, c + 48], fill=(255, 255, 255, 255))            # event dot
img.save(sys.argv[1])
PYEOF

echo "→ rendering .icns…"
mkdir -p "$TMP/LOLM.iconset"
for s in 16 32 128 256 512; do
  sips -z "$s" "$s" "$TMP/master.png" --out "$TMP/LOLM.iconset/icon_${s}x${s}.png" >/dev/null
  d2=$((s * 2))
  sips -z "$d2" "$d2" "$TMP/master.png" --out "$TMP/LOLM.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$TMP/LOLM.iconset" -o "$TMP/LOLM.icns"

echo "→ assembling $APP…"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$TMP/LOLM.icns" "$APP/Contents/Resources/LOLM.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>LOLM</string>
  <key>CFBundleDisplayName</key><string>LOLM</string>
  <key>CFBundleIdentifier</key><string>com.qira.lolm</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>LOLM</string>
  <key>CFBundleIconFile</key><string>LOLM</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

# Launcher: __REPO__ / __PY__ / __PORT__ are filled in below (quoted heredoc = no premature expansion)
cat > "$APP/Contents/MacOS/LOLM" <<'LAUNCH'
#!/bin/bash
# LOLM — start your local sovereign agent and open it.
REPO="__REPO__"
PY="__PY__"
PORT="__PORT__"
URL="http://127.0.0.1:$PORT/index.html"
mkdir -p "$HOME/.lolm"
LOG="$HOME/.lolm/server.log"
if curl -s -m 2 "http://127.0.0.1:$PORT/api/demo/brain" >/dev/null 2>&1; then
  open "$URL"; exit 0                                   # already running
fi
cd "$REPO" 2>/dev/null || { open "https://lolm.imagineqira.com"; exit 0; }
export LOLM_OPERATOR_LOCAL=1                            # operator runs on your machine
export DEMO_DEVICE="${DEMO_DEVICE:-mps}"                # Apple GPU for the graft
nohup "$PY" -m local_ui.server_public_demo >"$LOG" 2>&1 &
for i in $(seq 1 60); do
  curl -s -m 2 "http://127.0.0.1:$PORT/api/demo/brain" >/dev/null 2>&1 && break
  sleep 1
done
open "$URL"
LAUNCH

sed -i '' "s|__REPO__|$REPO|; s|__PY__|$PY|; s|__PORT__|$PORT|" "$APP/Contents/MacOS/LOLM"
chmod +x "$APP/Contents/MacOS/LOLM"
touch "$APP"                                            # nudge Finder to pick up the icon

echo ""
echo "✓ Installed: $APP"
echo "  Double-click it anytime — LOLM starts locally and opens in your browser."
echo "  (server log: ~/.lolm/server.log · keys: ~/.lolm/keys.env)"
