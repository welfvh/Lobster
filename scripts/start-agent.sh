#!/bin/bash
#
# Start an agent in a tmux session.
#
# Usage: start-agent.sh <agent-name>
# Example: start-agent.sh klaus
#

AGENT="${1:?Usage: start-agent.sh <agent-name>}"
WORKSPACE="$HOME/${AGENT}-workspace"

if [ ! -d "$WORKSPACE" ]; then
    echo "Error: Workspace not found at ${WORKSPACE}"
    echo "Run provision-agent.sh ${AGENT} first."
    exit 1
fi

if tmux has-session -t "$AGENT" 2>/dev/null; then
    echo "${AGENT} is already running in tmux session '${AGENT}'"
    exit 0
fi

tmux new-session -d -s "$AGENT" -c "$WORKSPACE" \
    "$HOME/lobster/scripts/agent-loop.sh $AGENT $WORKSPACE"

echo "${AGENT} started in tmux session '${AGENT}'"
echo "  Attach: tmux attach -t ${AGENT}"
echo "  Logs:   tail -f /tmp/${AGENT}-response.txt"
