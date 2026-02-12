# Lobster Handoff Document

## Identity
Lobster is an always-on AI assistant built on Claude Code. It processes messages from Telegram (and soon other channels) and responds to users.

## Owner
Drew (Telegram chat_id: 6645894734) - founder of Sidereal Press / Arcastro.

## Architecture
- MCP server at `/home/admin/lobster/src/mcp/inbox_server.py`
- Messages flow: Telegram -> `~/messages/inbox/` -> Lobster processes -> `~/messages/outbox/` -> Telegram
- Tasks stored in `~/messages/tasks.json`
- Scheduled jobs in `~/lobster/scheduled-tasks/`

## Current State
- Running on Debian cloud VM
- Python 3.13 with venv at `/home/admin/lobster/.venv/`
- GitHub repo: SiderealPress/lobster

## Key Patterns
- Dispatcher pattern: quick tasks (< 30s) handled directly, substantial tasks delegated to subagents
- PostToolUse hook auto-schedules self-check reminders after send_reply
- Health monitoring via heartbeat file

## Pending Items
- Task #2: Follow up with Edmunds about AI lecture at Arcastro
