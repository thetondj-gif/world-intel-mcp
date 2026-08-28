#!/bin/bash
# World Intel Collector control for macOS.
#
# Installs a portable per-user LaunchAgent that runs one real collection cycle
# daily. The installed plist is generated from the current checkout so no
# machine-specific repository path is committed.
#
# Usage:
#   collector-daemon.sh start|stop|restart|status|run-now|logs

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LABEL="com.agentic.intel-collector"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$HOME/.dawn/job-logs"
LOG="$LOG_DIR/world-intel-collector.log"
ERR_LOG="$LOG_DIR/world-intel-collector-error.log"
PYTHON="${WORLD_INTEL_PYTHON:-$REPO_ROOT/.venv/bin/python}"
HOUR="${WORLD_INTEL_DAILY_HOUR:-6}"
MINUTE="${WORLD_INTEL_DAILY_MINUTE:-30}"
DOMAIN="gui/$(id -u)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

require_python() {
    if [ ! -x "$PYTHON" ]; then
        echo -e "${RED}Collector Python is not executable:${NC} $PYTHON" >&2
        echo "Create the project .venv or set WORLD_INTEL_PYTHON to the intended interpreter." >&2
        exit 1
    fi
}

write_plist() {
    require_python
    mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON}</string>
    <string>-m</string>
    <string>world_intel_mcp.collector</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${REPO_ROOT}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>${HOUR}</integer>
    <key>Minute</key><integer>${MINUTE}</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>${LOG}</string>
  <key>StandardErrorPath</key>
  <string>${ERR_LOG}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>${REPO_ROOT}/.venv/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>PYTHONPATH</key>
    <string>${REPO_ROOT}/src</string>
    <key>WORLD_INTEL_LOG_LEVEL</key>
    <string>INFO</string>
  </dict>
</dict>
</plist>
EOF
    plutil -lint "$PLIST" >/dev/null
}

is_loaded() {
    launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1
}

case "${1:-help}" in
    start)
        write_plist
        if is_loaded; then
            launchctl bootout "$DOMAIN" "$PLIST" >/dev/null 2>&1 || true
        fi
        launchctl bootstrap "$DOMAIN" "$PLIST"
        echo -e "${GREEN}World Intel daily collector installed.${NC}"
        echo "Schedule: $(printf '%02d:%02d' "$HOUR" "$MINUTE") local time"
        echo "Repo: $REPO_ROOT"
        echo "Python: $PYTHON"
        ;;

    stop)
        if is_loaded; then
            launchctl bootout "$DOMAIN" "$PLIST"
            echo -e "${GREEN}World Intel collector unloaded.${NC}"
        else
            echo -e "${YELLOW}World Intel collector is not loaded.${NC}"
        fi
        ;;

    restart)
        "$0" stop || true
        "$0" start
        ;;

    run-now)
        require_python
        mkdir -p "$LOG_DIR"
        echo "Running one collection cycle from $REPO_ROOT"
        (
            cd "$REPO_ROOT"
            PYTHONPATH="$REPO_ROOT/src" WORLD_INTEL_LOG_LEVEL="${WORLD_INTEL_LOG_LEVEL:-INFO}" \
                "$PYTHON" -m world_intel_mcp.collector
        ) 2>&1 | tee -a "$LOG"
        ;;

    status)
        echo "=== World Intel Collector Status ==="
        echo "Repo: $REPO_ROOT"
        echo "Python: $PYTHON"
        echo "Schedule: $(printf '%02d:%02d' "$HOUR" "$MINUTE") local time"
        if is_loaded; then
            echo -e "State: ${GREEN}LOADED${NC}"
            launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -E 'state =|last exit code =|runs =' | head -10 || true
        else
            echo -e "State: ${RED}NOT LOADED${NC}"
        fi
        if [ -f "$LOG" ]; then
            echo "--- latest stdout ---"
            tail -n 8 "$LOG"
        else
            echo "No stdout log yet."
        fi
        if [ -s "$ERR_LOG" ]; then
            echo "--- latest stderr ---"
            tail -n 8 "$ERR_LOG"
        fi
        ;;

    logs)
        if [ "${2:-stdout}" = "err" ] || [ "${2:-stdout}" = "error" ] || [ "${2:-stdout}" = "stderr" ]; then
            touch "$ERR_LOG"
            tail -f "$ERR_LOG"
        else
            touch "$LOG"
            tail -f "$LOG"
        fi
        ;;

    help|*)
        echo "World Intel Collector Control"
        echo "Usage: $0 {start|stop|restart|status|run-now|logs}"
        echo ""
        echo "start    Install/reload the daily LaunchAgent using this checkout"
        echo "stop     Unload the LaunchAgent"
        echo "restart  Reinstall and reload the LaunchAgent"
        echo "status   Show launchd state and latest evidence"
        echo "run-now  Run one real collection cycle synchronously"
        echo "logs     Follow stdout; use 'logs err' for stderr"
        ;;
esac
