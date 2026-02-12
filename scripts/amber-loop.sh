#!/bin/bash
#
# Amber always-on loop using claude -p (print mode)
#
# Key constraints discovered:
# 1. Use --permission-mode bypassPermissions (NOT --dangerously-skip-permissions)
# 2. Do NOT use timeout command (causes SIGTSTP on child process)
# 3. Use file redirect > file (NOT $() subshell capture)
# 4. Each -p call needs a fresh session OR use --continue
#

export PATH="$HOME/.local/bin:$PATH"
cd /home/lobster/amber-workspace

HEARTBEAT="$HOME/amber-workspace/logs/claude-heartbeat"
OUTPUT_FILE="/tmp/amber-response.txt"
mkdir -p "$(dirname "$HEARTBEAT")"

echo "[$(date)] Amber loop starting..."

# First iteration: full startup with fresh session
FIRST_RUN=true

while true; do
    touch "$HEARTBEAT"
    echo "[$(date)] Sending prompt to Amber..."

    if [ "$FIRST_RUN" = true ]; then
        # Initial startup — creates a new session
        claude -p 'Read CLAUDE.md and soul.md. You are Amber. Follow the Startup Sequence in CLAUDE.md exactly. After completing startup, call wait_for_messages(timeout=30) and report what you find. Be concise.' \
            --permission-mode bypassPermissions \
            --output-format text \
            > "$OUTPUT_FILE" 2>/tmp/amber-stderr.log
        EXIT_CODE=$?
        FIRST_RUN=false
    else
        # Subsequent iterations: continue previous session
        claude -p 'Call wait_for_messages(timeout=30) to listen for messages. Process any you find. If you get messages, handle them — reply to the user via send_reply(chat_id=716197220, text=...) for Telegram messages. Report back briefly what happened.' \
            --permission-mode bypassPermissions \
            --output-format text \
            --continue \
            > "$OUTPUT_FILE" 2>/tmp/amber-stderr.log
        EXIT_CODE=$?
    fi

    if [ $EXIT_CODE -ne 0 ]; then
        echo "[$(date)] Claude exited with code $EXIT_CODE"
        cat "$OUTPUT_FILE" 2>/dev/null
        # If session is stale, start fresh
        FIRST_RUN=true
        sleep 5
        continue
    fi

    echo "[$(date)] Amber response:"
    cat "$OUTPUT_FILE"
    echo "---"

    touch "$HEARTBEAT"
    sleep 2
done
