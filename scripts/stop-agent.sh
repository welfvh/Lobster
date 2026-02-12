#!/bin/bash
#
# Stop an agent by killing its tmux session.
#
# Usage: stop-agent.sh <agent-name>
# Example: stop-agent.sh klaus
#

AGENT="${1:?Usage: stop-agent.sh <agent-name>}"

if tmux has-session -t "$AGENT" 2>/dev/null; then
    tmux kill-session -t "$AGENT"
    echo "${AGENT} stopped"
else
    echo "${AGENT} is not running"
fi
