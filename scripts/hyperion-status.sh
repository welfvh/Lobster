#!/bin/bash
#
# Hyperion Status - Check if Hyperion is running
#

SESSION_NAME="hyperion"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=== Hyperion Status ==="
echo ""

# Check tmux session
if tmux -L hyperion has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo -e "Claude Session: ${GREEN}RUNNING${NC}"
    echo "  Attach: tmux -L hyperion attach -t $SESSION_NAME"
else
    echo -e "Claude Session: ${RED}NOT RUNNING${NC}"
    echo "  Start:  ~/hyperion/scripts/start-hyperion.sh"
fi

echo ""

# Check telegram bot
if systemctl is-active --quiet hyperion-router; then
    echo -e "Telegram Bot:   ${GREEN}RUNNING${NC}"
else
    echo -e "Telegram Bot:   ${RED}NOT RUNNING${NC}"
    echo "  Start:  sudo systemctl start hyperion-router"
fi

echo ""

# Check inbox
INBOX_COUNT=$(ls -1 ~/messages/inbox/*.json 2>/dev/null | wc -l)
echo "Inbox Messages: $INBOX_COUNT"

# Check outbox
OUTBOX_COUNT=$(ls -1 ~/messages/outbox/*.json 2>/dev/null | wc -l)
echo "Pending Replies: $OUTBOX_COUNT"

echo ""
