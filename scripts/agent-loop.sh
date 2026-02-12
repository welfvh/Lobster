#!/bin/bash
#
# Generic agent loop using claude -p (print mode)
#
# Usage: agent-loop.sh <agent-name> [workspace-dir]
# Example: agent-loop.sh klaus ~/klaus-workspace
#
# Constraints (discovered with Amber):
# 1. Use --permission-mode bypassPermissions (NOT --dangerously-skip-permissions)
# 2. Do NOT use timeout command (causes SIGTSTP on child process)
# 3. Use file redirect > file (NOT $() subshell capture)
# 4. Each -p call needs a fresh session OR use --continue
#

AGENT="${1:?Usage: agent-loop.sh <agent-name> [workspace-dir]}"
WORKSPACE="${2:-$HOME/${AGENT}-workspace}"

export PATH="$HOME/.local/bin:$PATH"
cd "$WORKSPACE"

HEARTBEAT="$WORKSPACE/logs/claude-heartbeat"
OUTPUT_FILE="/tmp/${AGENT}-response.txt"
STDERR_FILE="/tmp/${AGENT}-stderr.log"
mkdir -p "$(dirname "$HEARTBEAT")" "$WORKSPACE/logs"

echo "[$(date)] ${AGENT} loop starting..."
echo "[$(date)] Workspace: $WORKSPACE"

# First iteration: fresh session with startup sequence
FIRST_RUN=true

while true; do
    touch "$HEARTBEAT"
    echo "[$(date)] Sending prompt to ${AGENT}..."

    if [ "$FIRST_RUN" = true ]; then
        # Initial startup -- creates a new session, reads identity files
        claude -p "Read CLAUDE.md and soul.md. You are ${AGENT^}. Follow the Startup Sequence in CLAUDE.md exactly. After completing startup, call wait_for_messages(timeout=30) and report what you find. Be concise." \
            --permission-mode bypassPermissions \
            --output-format text \
            > "$OUTPUT_FILE" 2>"$STDERR_FILE"
        EXIT_CODE=$?
        FIRST_RUN=false
    else
        # Subsequent iterations: continue previous session
        claude -p "Call wait_for_messages(timeout=30) to listen for messages. Process any you find. Handle them according to your role. Report back briefly what happened." \
            --permission-mode bypassPermissions \
            --output-format text \
            --continue \
            > "$OUTPUT_FILE" 2>"$STDERR_FILE"
        EXIT_CODE=$?
    fi

    if [ $EXIT_CODE -ne 0 ]; then
        echo "[$(date)] Claude exited with code $EXIT_CODE"
        head -20 "$OUTPUT_FILE" 2>/dev/null
        # If session is stale, start fresh
        FIRST_RUN=true
        sleep 5
        continue
    fi

    echo "[$(date)] ${AGENT} response:"
    head -20 "$OUTPUT_FILE"
    echo "---"

    touch "$HEARTBEAT"
    sleep 2
done
