#!/bin/bash
#
# Provision a new agent workspace and message directories.
#
# Usage: provision-agent.sh <agent-name>
# Example: provision-agent.sh klaus
#
# Creates:
#   ~/NAME-workspace/           (workspace directory)
#   ~/NAME-workspace/logs/      (agent logs)
#   ~/NAME-workspace/.mcp.json  (MCP server config)
#   ~/NAME-workspace/CLAUDE.md  (placeholder if not exists)
#   ~/NAME-workspace/soul.md    (placeholder if not exists)
#   ~/messages/NAME-inbox/      (incoming messages)
#   ~/messages/NAME-outbox/     (outgoing replies)
#   ~/messages/NAME-processed/  (handled messages)
#   ~/messages/NAME-sent/       (sent reply archive)
#   ~/messages/NAME-task-outputs/ (scheduled task outputs)
#   ~/messages/NAME-tasks.json  (task list)

set -e

AGENT="${1:?Usage: provision-agent.sh <agent-name>}"
AGENT=$(echo "$AGENT" | tr '[:upper:]' '[:lower:]')

WORKSPACE="$HOME/${AGENT}-workspace"
MSG_BASE="$HOME/messages"
LOBSTER_DIR="$HOME/lobster"

echo "Provisioning agent: ${AGENT}"
echo "  Workspace: ${WORKSPACE}"
echo ""

# Create workspace
mkdir -p "$WORKSPACE/logs"
echo "  Created ${WORKSPACE}/logs/"

# Create message directories
mkdir -p "$MSG_BASE/${AGENT}-inbox"
mkdir -p "$MSG_BASE/${AGENT}-outbox"
mkdir -p "$MSG_BASE/${AGENT}-processed"
mkdir -p "$MSG_BASE/${AGENT}-sent"
mkdir -p "$MSG_BASE/${AGENT}-task-outputs"
echo "  Created message directories in ${MSG_BASE}/"

# Create .mcp.json pointing to the universal agent inbox server
cat > "$WORKSPACE/.mcp.json" << EOF
{
  "mcpServers": {
    "${AGENT}-inbox": {
      "type": "stdio",
      "command": "${LOBSTER_DIR}/.venv/bin/python",
      "args": ["${LOBSTER_DIR}/src/mcp/agent_inbox_server.py", "--agent", "${AGENT}"]
    },
    "context": {
      "type": "http",
      "url": "https://context-mcp.potential.workers.dev/mcp"
    }
  }
}
EOF
echo "  Created ${WORKSPACE}/.mcp.json"

# Create placeholder CLAUDE.md if it doesn't exist
if [ ! -f "$WORKSPACE/CLAUDE.md" ]; then
    # Capitalize first letter of agent name
    DISPLAY_NAME="$(echo "${AGENT}" | sed 's/\b\(.\)/\u\1/g')"
    cat > "$WORKSPACE/CLAUDE.md" << EOF
# ${DISPLAY_NAME} Agent

## Role
TODO: Define role and responsibilities.

## Available Tools
- ${AGENT}-inbox MCP: wait_for_messages, check_inbox, send_reply, mark_processed, etc.
- context MCP: profile, captures, reflections
- IPC: send_to_lobster, send_to_amber, send_to_klaus, etc.

## Behavior
TODO: Define behavioral guidelines.
EOF
    echo "  Created ${WORKSPACE}/CLAUDE.md (placeholder)"
else
    echo "  CLAUDE.md already exists, skipping"
fi

# Create placeholder soul.md if it doesn't exist
if [ ! -f "$WORKSPACE/soul.md" ]; then
    DISPLAY_NAME="$(echo "${AGENT}" | sed 's/\b\(.\)/\u\1/g')"
    cat > "$WORKSPACE/soul.md" << EOF
# ${DISPLAY_NAME} - Soul

## Personality
TODO: Define personality, voice, and values.

## Communication Style
TODO: Define communication style.

## Values
TODO: Define core values.
EOF
    echo "  Created ${WORKSPACE}/soul.md (placeholder)"
else
    echo "  soul.md already exists, skipping"
fi

# Initialize tasks file if it doesn't exist
TASKS_FILE="$MSG_BASE/${AGENT}-tasks.json"
if [ ! -f "$TASKS_FILE" ]; then
    echo '{"tasks": [], "next_id": 1}' > "$TASKS_FILE"
    echo "  Created ${TASKS_FILE}"
else
    echo "  Tasks file already exists, skipping"
fi

echo ""
echo "Agent '${AGENT}' provisioned successfully."
echo ""
echo "Next steps:"
echo "  1. Edit ${WORKSPACE}/CLAUDE.md with role and responsibilities"
echo "  2. Edit ${WORKSPACE}/soul.md with personality and voice"
echo "  3. Start with: ~/lobster/scripts/agent-loop.sh ${AGENT}"
echo "  Or in tmux: tmux new-session -d -s ${AGENT} ~/lobster/scripts/agent-loop.sh ${AGENT}"
