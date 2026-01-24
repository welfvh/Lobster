#!/bin/bash
#
# Stop Hyperion - Gracefully stop the always-on Claude session
#

SESSION_NAME="hyperion"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

if tmux -L hyperion has-session -t "$SESSION_NAME" 2>/dev/null; then
    info "Stopping Hyperion..."
    tmux -L hyperion kill-session -t "$SESSION_NAME"
    info "Hyperion stopped."
else
    warn "Hyperion is not running."
fi
