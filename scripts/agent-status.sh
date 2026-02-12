#!/bin/bash
#
# Show status of all agents (tmux session + heartbeat).
#
# Usage: agent-status.sh
#

echo "Agent Status"
echo "============"
echo ""

for agent in lobster amber klaus jordan scout herald; do
    WORKSPACE="$HOME/${agent}-workspace"
    HEARTBEAT="$WORKSPACE/logs/claude-heartbeat"

    if [ "$agent" = "lobster" ]; then
        SESSION="hyperion"
    else
        SESSION="$agent"
    fi

    if tmux has-session -t "$SESSION" 2>/dev/null; then
        if [ -f "$HEARTBEAT" ]; then
            AGE=$(( $(date +%s) - $(stat -c %Y "$HEARTBEAT" 2>/dev/null || echo 0) ))
            if [ $AGE -lt 120 ]; then
                STATUS="RUNNING (heartbeat ${AGE}s ago)"
            else
                STATUS="RUNNING (heartbeat stale: ${AGE}s ago)"
            fi
        else
            STATUS="RUNNING (no heartbeat)"
        fi
    else
        STATUS="STOPPED"
    fi

    # Get inbox count
    if [ "$agent" = "lobster" ]; then
        INBOX_DIR="$HOME/messages/inbox"
    else
        INBOX_DIR="$HOME/messages/${agent}-inbox"
    fi
    INBOX_COUNT=$(ls "$INBOX_DIR"/*.json 2>/dev/null | wc -l)

    printf "  %-10s %s  (inbox: %d)\n" "$agent" "$STATUS" "$INBOX_COUNT"
done

echo ""
echo "Memory usage:"
ps aux | grep -E "claude|python.*inbox_server|python.*agent_inbox|python.*slack_gateway" | grep -v grep | awk '{sum += $6} END {printf "  Total: %.0f MB\n", sum/1024}'
