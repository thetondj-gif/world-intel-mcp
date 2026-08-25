#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
UID_NUM="$(id -u)"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/world-intel-mcp"
mkdir -p "$LAUNCH_DIR" "$LOG_DIR"

if [ ! -x "$PY" ]; then
  python3 -m venv "$VENV"
fi
"$PY" -m pip install --upgrade pip
"$PY" -m pip install -r "$ROOT/requirements.txt"

cat > "$LAUNCH_DIR/com.agentic.world-intel-dashboard.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.agentic.world-intel-dashboard</string>
<key>ProgramArguments</key><array><string>$PY</string><string>-m</string><string>world_intel_mcp.dashboard.app</string></array>
<key>WorkingDirectory</key><string>$ROOT</string>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>$LOG_DIR/dashboard.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/dashboard-error.log</string>
<key>EnvironmentVariables</key><dict>
<key>PYTHONPATH</key><string>$ROOT/src</string>
<key>WORLD_INTEL_DASHBOARD_HOST</key><string>127.0.0.1</string>
<key>WORLD_INTEL_DASHBOARD_PORT</key><string>8501</string>
</dict>
</dict></plist>
PLIST

cat > "$LAUNCH_DIR/com.agentic.intel-collector.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.agentic.intel-collector</string>
<key>ProgramArguments</key><array><string>$PY</string><string>-m</string><string>world_intel_mcp.collector</string><string>--daemon</string><string>--interval</string><string>300</string></array>
<key>WorkingDirectory</key><string>$ROOT</string>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/><key>ThrottleInterval</key><integer>30</integer>
<key>StandardOutPath</key><string>$LOG_DIR/collector.log</string>
<key>StandardErrorPath</key><string>$LOG_DIR/collector-error.log</string>
<key>EnvironmentVariables</key><dict><key>PYTHONPATH</key><string>$ROOT/src</string><key>WORLD_INTEL_LOG_LEVEL</key><string>INFO</string></dict>
</dict></plist>
PLIST

for LABEL in com.agentic.world-intel-dashboard com.agentic.intel-collector; do
  launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_NUM" "$LAUNCH_DIR/$LABEL.plist"
  launchctl kickstart -k "gui/$UID_NUM/$LABEL"
done

sleep 3
curl -fsS http://127.0.0.1:8501/api/health
printf '\nWorld Intel standalone app: http://127.0.0.1:8501\n'
printf 'Collector interval: 300 seconds\n'
