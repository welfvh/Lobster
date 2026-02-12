#!/bin/bash
# Watchdog: checks if Lobster and Amber Claude sessions are alive
# Run via cron every 5 minutes: */5 * * * * /home/lobster/lobster/scripts/watchdog.sh
#
# Key fix: uses the expect wrapper for restarts (handles Claude's startup prompt
# timing correctly) and kills orphan claude processes before restarting.

LOBSTER_HEARTBEAT="$HOME/lobster-workspace/logs/claude-heartbeat"
AMBER_HEARTBEAT="$HOME/amber-workspace/logs/claude-heartbeat"
MAX_STALE_SECONDS=600  # 10 minutes

now=$(date +%s)

check_session() {
    local name="$1"
    local heartbeat="$2"
    local tmux_session="$3"
    local workspace="$4"

    if [ ! -f "$heartbeat" ]; then
        echo "[$name] No heartbeat file — session may never have started"
        return 1
    fi

    last_modified=$(stat -c %Y "$heartbeat" 2>/dev/null)
    age=$((now - last_modified))

    if [ "$age" -gt "$MAX_STALE_SECONDS" ]; then
        echo "[$name] Heartbeat stale (${age}s old). Restarting..."

        # Kill existing tmux session
        tmux kill-session -t "$tmux_session" 2>/dev/null
        sleep 2

        # Kill any orphan claude processes in this workspace
        # (they can linger after tmux dies, eating memory)
        pkill -u lobster -f "claude.*$workspace" 2>/dev/null
        sleep 1

        # Touch heartbeat to prevent immediate re-trigger on next watchdog run
        # (gives the new session time to start its own heartbeat loop)
        touch "$heartbeat"

        # Use the expect wrapper for Lobster — it handles Claude's startup
        # prompt timing correctly (waits for the ❯ prompt before sending)
        if [ "$name" = "Lobster" ]; then
            tmux new-session -d -s "$tmux_session" -c "$workspace" "$HOME/lobster/scripts/claude-wrapper.exp"
        else
            tmux new-session -d -s "$tmux_session" -c "$workspace" "$HOME/lobster/scripts/amber-loop.sh"
        fi

        echo "[$name] Restarted via wrapper script"
        return 0
    fi

    echo "[$name] OK (heartbeat ${age}s ago)"
}

check_session "Lobster" "$LOBSTER_HEARTBEAT" "hyperion" "$HOME/lobster-workspace"

check_amber() {
    local heartbeat="$AMBER_HEARTBEAT"
    if [ ! -f "$heartbeat" ]; then
        echo "[Amber] No heartbeat file — starting loop"
        tmux kill-session -t amber 2>/dev/null
        sleep 2
        tmux new-session -d -s amber -c "$HOME/amber-workspace" "$HOME/lobster/scripts/amber-loop.sh"
        echo "[Amber] Loop started"
        return 0
    fi

    last_modified=$(stat -c %Y "$heartbeat" 2>/dev/null)
    age=$((now - last_modified))

    if [ "$age" -gt "$MAX_STALE_SECONDS" ]; then
        echo "[Amber] Heartbeat stale (${age}s old). Restarting loop..."
        tmux kill-session -t amber 2>/dev/null
        sleep 2
        pkill -u lobster -f "claude.*amber-workspace" 2>/dev/null
        sleep 1
        touch "$heartbeat"
        tmux new-session -d -s amber -c "$HOME/amber-workspace" "$HOME/lobster/scripts/amber-loop.sh"
        echo "[Amber] Loop restarted"
        return 0
    fi

    echo "[Amber] OK (heartbeat ${age}s ago)"
}

check_amber

# Check bots are running
if ! pgrep -f "lobster_bot.py" > /dev/null; then
    echo "[Lobster Bot] Not running — needs manual restart (token required)"
fi

if ! pgrep -f "amber_bot.py" > /dev/null; then
    echo "[Amber Bot] Not running — needs manual restart (token required)"
fi
