#!/usr/bin/env python3
"""
Universal Agent Inbox MCP Server

Parameterized replacement for per-agent inbox server copies.
Takes --agent <name> as CLI argument and derives all paths from the agent name.

Usage:
    agent_inbox_server.py --agent <name>

Paths derived from agent name:
    inbox:     ~/messages/<agent>-inbox/    (or ~/messages/inbox/ for "lobster")
    outbox:    ~/messages/<agent>-outbox/   (or ~/messages/outbox/ for "lobster")
    processed: ~/messages/<agent>-processed/ (or ~/messages/processed/ for "lobster")
    sent:      ~/messages/<agent>-sent/     (or ~/messages/sent/ for "lobster")
    tasks:     ~/messages/<agent>-tasks.json (or ~/messages/tasks.json for "lobster")

IPC tools (send_to_<agent>) are dynamically generated from agents.json config.
"""

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# MCP SDK
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# =============================================================================
# CLI Argument Parsing
# =============================================================================

parser = argparse.ArgumentParser(description="Universal Agent Inbox MCP Server")
parser.add_argument("--agent", required=True, help="Agent name (e.g., lobster, klaus, scout)")
args = parser.parse_args()

AGENT = args.agent.lower()

# =============================================================================
# Path Configuration
# =============================================================================

BASE_DIR = Path.home() / "messages"

if AGENT == "lobster":
    INBOX_DIR = BASE_DIR / "inbox"
    OUTBOX_DIR = BASE_DIR / "outbox"
    PROCESSED_DIR = BASE_DIR / "processed"
    SENT_DIR = BASE_DIR / "sent"
    TASKS_FILE = BASE_DIR / "tasks.json"
    TASK_OUTPUTS_DIR = BASE_DIR / "task-outputs"
    AUDIO_DIR = BASE_DIR / "audio"
elif AGENT == "amber":
    INBOX_DIR = BASE_DIR / "amber-inbox"
    OUTBOX_DIR = BASE_DIR / "amber-outbox"
    PROCESSED_DIR = BASE_DIR / "amber-processed"
    SENT_DIR = BASE_DIR / "amber-sent"
    TASKS_FILE = BASE_DIR / "amber-tasks.json"
    TASK_OUTPUTS_DIR = BASE_DIR / "amber-task-outputs"
    AUDIO_DIR = BASE_DIR / "amber-audio"
else:
    INBOX_DIR = BASE_DIR / f"{AGENT}-inbox"
    OUTBOX_DIR = BASE_DIR / f"{AGENT}-outbox"
    PROCESSED_DIR = BASE_DIR / f"{AGENT}-processed"
    SENT_DIR = BASE_DIR / f"{AGENT}-sent"
    TASKS_FILE = BASE_DIR / f"{AGENT}-tasks.json"
    TASK_OUTPUTS_DIR = BASE_DIR / f"{AGENT}-task-outputs"
    AUDIO_DIR = BASE_DIR / f"{AGENT}-audio"

# Heartbeat file for health monitoring
WORKSPACE_DIR = Path.home() / f"{AGENT}-workspace"
HEARTBEAT_FILE = WORKSPACE_DIR / "logs" / "claude-heartbeat"

# Scheduled Tasks Directories (shared infrastructure)
SCHEDULED_TASKS_DIR = Path.home() / "lobster" / "scheduled-tasks"
SCHEDULED_JOBS_FILE = SCHEDULED_TASKS_DIR / "jobs.json"
SCHEDULED_TASKS_TASKS_DIR = SCHEDULED_TASKS_DIR / "tasks"
SCHEDULED_TASKS_LOGS_DIR = SCHEDULED_TASKS_DIR / "logs"

# Ensure directories exist
for d in [INBOX_DIR, OUTBOX_DIR, PROCESSED_DIR, SENT_DIR, AUDIO_DIR, TASK_OUTPUTS_DIR,
          SCHEDULED_TASKS_DIR, SCHEDULED_TASKS_TASKS_DIR, SCHEDULED_TASKS_LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# =============================================================================
# Agent Configuration
# =============================================================================

AGENTS_CONFIG_PATH = Path.home() / "lobster" / "config" / "agents.json"

def load_agents_config() -> dict:
    """Load agents configuration from agents.json."""
    try:
        return json.loads(AGENTS_CONFIG_PATH.read_text())
    except Exception:
        return {}

AGENTS_CONFIG = load_agents_config()

# Get this agent's display info
AGENT_CONFIG = AGENTS_CONFIG.get(AGENT, {})
AGENT_DISPLAY_NAME = AGENT_CONFIG.get("display_name", AGENT.title())

# =============================================================================
# Initialize Tasks
# =============================================================================

if not TASKS_FILE.exists():
    TASKS_FILE.write_text(json.dumps({"tasks": [], "next_id": 1}, indent=2))

if not SCHEDULED_JOBS_FILE.exists():
    SCHEDULED_JOBS_FILE.write_text(json.dumps({"jobs": {}}, indent=2))

# =============================================================================
# Source Configurations
# =============================================================================

SOURCES = {
    "telegram": {"name": "Telegram", "enabled": True},
    "slack": {"name": "Slack", "enabled": True},
    "internal": {"name": "Internal (IPC)", "enabled": True},
}

server = Server(f"{AGENT}-inbox")

# =============================================================================
# Heartbeat
# =============================================================================

def touch_heartbeat():
    """Touch heartbeat file to signal agent is alive and processing."""
    try:
        HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_FILE.touch()
    except Exception:
        pass


# =============================================================================
# IPC Tool Generation
# =============================================================================

def get_ipc_targets() -> list[str]:
    """Get list of other agents this agent can send messages to."""
    return [name for name in AGENTS_CONFIG.keys() if name != AGENT]


def build_ipc_tools() -> list[Tool]:
    """Dynamically build send_to_<agent> tools for all other known agents."""
    tools = []
    for other_agent in get_ipc_targets():
        other_config = AGENTS_CONFIG[other_agent]
        display_name = other_config.get("display_name", other_agent.title())
        role = other_config.get("role", "agent")
        tools.append(Tool(
            name=f"send_to_{other_agent}",
            description=f"Send a message to {display_name} ({role}). The message will appear in their inbox. Use this for inter-agent communication.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": f"The message text to send to {display_name}.",
                    },
                },
                "required": ["text"],
            },
        ))
    return tools


async def handle_send_to_agent(target_agent: str, args: dict) -> list[TextContent]:
    """Send a message to another agent's inbox."""
    text = args.get("text", "").strip()
    if not text:
        return [TextContent(type="text", text="Error: text is required.")]

    # Determine target inbox directory
    if target_agent == "lobster":
        target_inbox = BASE_DIR / "inbox"
    elif target_agent == "amber":
        target_inbox = BASE_DIR / "amber-inbox"
    else:
        target_inbox = BASE_DIR / f"{target_agent}-inbox"

    target_inbox.mkdir(parents=True, exist_ok=True)

    msg_id = f"ipc_{int(time.time() * 1000)}_{AGENT}"
    msg_data = {
        "id": msg_id,
        "source": "internal",
        "chat_id": AGENT,
        "user_name": AGENT_DISPLAY_NAME,
        "text": text,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": "text",
    }

    msg_file = target_inbox / f"{msg_id}.json"
    with open(msg_file, "w") as f:
        json.dump(msg_data, f, indent=2)

    target_display = AGENTS_CONFIG.get(target_agent, {}).get("display_name", target_agent.title())
    return [TextContent(type="text", text=f"Message sent to {target_display}: {text[:100]}{'...' if len(text) > 100 else ''}")]


# =============================================================================
# Tool Listing
# =============================================================================

@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    tools = [
        Tool(
            name="wait_for_messages",
            description="Block and wait for new messages to arrive. This is the core tool for the always-on loop. Returns immediately if messages exist, otherwise waits until a message arrives or timeout. Use this in your main loop: wait_for_messages -> process -> repeat.",
            inputSchema={
                "type": "object",
                "properties": {
                    "timeout": {
                        "type": "integer",
                        "description": "Maximum seconds to wait. Default 300 (5 minutes). After timeout, returns with a prompt to call again.",
                        "default": 300,
                    },
                },
            },
        ),
        Tool(
            name="check_inbox",
            description="Check for new messages in the inbox from all sources (Telegram, SMS, Signal, etc.). Returns unprocessed messages. For the always-on loop, prefer wait_for_messages which blocks until messages arrive.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Filter by source (telegram, sms, signal). Leave empty for all sources.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of messages to return. Default 10.",
                        "default": 10,
                    },
                },
            },
        ),
        Tool(
            name="send_reply",
            description="Send a reply to a message. The reply will be routed back to the original source (Telegram, Slack, SMS, etc.). Supports optional inline keyboard buttons for Telegram and thread replies for Slack.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {
                        "oneOf": [{"type": "integer"}, {"type": "string"}],
                        "description": "The chat/channel ID to reply to (from the original message). Integer for Telegram, string for Slack.",
                    },
                    "text": {
                        "type": "string",
                        "description": "The reply text to send.",
                    },
                    "source": {
                        "type": "string",
                        "description": "The source to reply via (telegram, slack, sms, signal). Default: telegram.",
                        "default": "telegram",
                    },
                    "thread_ts": {
                        "type": "string",
                        "description": "Slack thread timestamp. If provided, reply will be sent as a thread reply. Get this from the original message's thread_ts or slack_ts field.",
                    },
                    "buttons": {
                        "type": "array",
                        "description": "Optional inline keyboard buttons (Telegram only). Format: [[\"Btn1\", \"Btn2\"], [\"Btn3\"]] for simple buttons (text=callback_data), or [[{\"text\": \"Label\", \"callback_data\": \"value\"}]] for explicit callback data.",
                        "items": {
                            "type": "array",
                            "description": "A row of buttons",
                            "items": {
                                "oneOf": [
                                    {"type": "string", "description": "Simple button (text is also callback_data)"},
                                    {
                                        "type": "object",
                                        "properties": {
                                            "text": {"type": "string", "description": "Button label"},
                                            "callback_data": {"type": "string", "description": "Data sent when pressed"}
                                        },
                                        "required": ["text"]
                                    }
                                ]
                            }
                        }
                    },
                },
                "required": ["chat_id", "text"],
            },
        ),
        Tool(
            name="mark_processed",
            description="Mark a message as processed and move it out of the inbox.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "The message ID to mark as processed.",
                    },
                },
                "required": ["message_id"],
            },
        ),
        Tool(
            name="list_sources",
            description="List all available message sources and their status.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_stats",
            description="Get inbox statistics: message counts, sources, etc.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_conversation_history",
            description="Retrieve past messages from conversation history - both received messages and sent replies. Supports pagination, filtering by chat_id, and text search. Use this to scroll back through previous conversations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "chat_id": {
                        "oneOf": [{"type": "integer"}, {"type": "string"}],
                        "description": "Filter by chat ID to see conversation with a specific user. Leave empty for all conversations.",
                    },
                    "search": {
                        "type": "string",
                        "description": "Search text to filter messages (case-insensitive). Searches in message text content.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of messages to return. Default 20, max 100.",
                        "default": 20,
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Number of messages to skip (for pagination). Default 0. Messages are returned newest-first, so offset=0 gives the most recent messages.",
                        "default": 0,
                    },
                    "direction": {
                        "type": "string",
                        "description": "Filter by direction: 'received' for incoming messages only, 'sent' for outgoing replies only, or 'all' for both. Default 'all'.",
                        "default": "all",
                    },
                    "source": {
                        "type": "string",
                        "description": "Filter by source (telegram, slack, etc.). Leave empty for all sources.",
                    },
                },
            },
        ),
        # Task Management Tools
        Tool(
            name="list_tasks",
            description=f"List all tasks with their status. Tasks are shared across all {AGENT_DISPLAY_NAME} sessions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filter by status: pending, in_progress, completed, or all (default).",
                        "default": "all",
                    },
                },
            },
        ),
        Tool(
            name="create_task",
            description="Create a new task.",
            inputSchema={
                "type": "object",
                "properties": {
                    "subject": {
                        "type": "string",
                        "description": "Brief title for the task.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Detailed description of what needs to be done.",
                    },
                },
                "required": ["subject"],
            },
        ),
        Tool(
            name="update_task",
            description="Update a task's status or details.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "The task ID to update."},
                    "status": {"type": "string", "description": "New status: pending, in_progress, or completed."},
                    "subject": {"type": "string", "description": "New subject (optional)."},
                    "description": {"type": "string", "description": "New description (optional)."},
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="get_task",
            description="Get details of a specific task.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "The task ID to retrieve."},
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="delete_task",
            description="Delete a task.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "The task ID to delete."},
                },
                "required": ["task_id"],
            },
        ),
        Tool(
            name="transcribe_audio",
            description="Transcribe a voice message to text using local whisper.cpp (small model). Use this for messages with type='voice'. Runs entirely locally using whisper.cpp - no cloud API or API key needed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "The message ID of the voice message to transcribe.",
                    },
                },
                "required": ["message_id"],
            },
        ),
        Tool(
            name="fetch_page",
            description="Fetch a web page using a headless browser (Playwright/Chromium). Renders JavaScript fully before extracting text content. Ideal for Twitter/X links, SPAs, and other JS-heavy pages. Returns cleaned text content, not raw HTML.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch. Will be loaded in a headless Chromium browser."},
                    "wait_seconds": {"type": "number", "description": "Extra seconds to wait after page load for JS rendering. Default 3. Increase for slow-loading pages.", "default": 3},
                    "timeout": {"type": "integer", "description": "Maximum seconds before giving up. Default 30.", "default": 30},
                },
                "required": ["url"],
            },
        ),
        # Scheduled Jobs Tools
        Tool(
            name="create_scheduled_job",
            description="Create a new scheduled job that runs automatically via cron. Jobs run in separate Claude instances and write outputs to the task-outputs inbox.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Unique name for the job (lowercase, hyphens allowed, e.g., 'morning-weather')."},
                    "schedule": {"type": "string", "description": "Cron schedule expression (e.g., '0 9 * * *' for 9am daily, '*/30 * * * *' for every 30 mins)."},
                    "context": {"type": "string", "description": "Instructions for the job. Describe what the scheduled task should do."},
                },
                "required": ["name", "schedule", "context"],
            },
        ),
        Tool(
            name="list_scheduled_jobs",
            description="List all scheduled jobs with their status and schedules.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_scheduled_job",
            description="Get detailed information about a specific scheduled job.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The job name to retrieve."},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="update_scheduled_job",
            description="Update an existing scheduled job's schedule, context, or enabled status.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The job name to update."},
                    "schedule": {"type": "string", "description": "New cron schedule (optional)."},
                    "context": {"type": "string", "description": "New instructions for the job (optional)."},
                    "enabled": {"type": "boolean", "description": "Enable or disable the job (optional)."},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="delete_scheduled_job",
            description="Delete a scheduled job and remove it from crontab.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The job name to delete."},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="check_task_outputs",
            description="Check recent outputs from scheduled tasks. Use this to review what your scheduled jobs have done.",
            inputSchema={
                "type": "object",
                "properties": {
                    "since": {"type": "string", "description": "Only show outputs since this ISO timestamp (optional)."},
                    "limit": {"type": "integer", "description": "Maximum number of outputs to return. Default 10.", "default": 10},
                    "job_name": {"type": "string", "description": "Filter by job name (optional)."},
                },
            },
        ),
        Tool(
            name="write_task_output",
            description="Write output from a scheduled task. Used by task instances to record their results.",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_name": {"type": "string", "description": "The name of the job writing output."},
                    "output": {"type": "string", "description": "The output/result to record."},
                    "status": {"type": "string", "description": "Status: 'success' or 'failed'. Default 'success'.", "default": "success"},
                },
                "required": ["job_name", "output"],
            },
        ),
    ]

    # Add dynamically-generated IPC tools
    tools.extend(build_ipc_tools())

    return tools


# =============================================================================
# Tool Call Dispatcher
# =============================================================================

@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""

    # Check for IPC tools first (send_to_<agent>)
    if name.startswith("send_to_"):
        target_agent = name[len("send_to_"):]
        if target_agent in AGENTS_CONFIG:
            return await handle_send_to_agent(target_agent, arguments)

    if name == "wait_for_messages":
        return await handle_wait_for_messages(arguments)
    elif name == "check_inbox":
        return await handle_check_inbox(arguments)
    elif name == "send_reply":
        return await handle_send_reply(arguments)
    elif name == "mark_processed":
        return await handle_mark_processed(arguments)
    elif name == "list_sources":
        return await handle_list_sources(arguments)
    elif name == "get_stats":
        return await handle_get_stats(arguments)
    elif name == "get_conversation_history":
        return await handle_get_conversation_history(arguments)
    elif name == "list_tasks":
        return await handle_list_tasks(arguments)
    elif name == "create_task":
        return await handle_create_task(arguments)
    elif name == "update_task":
        return await handle_update_task(arguments)
    elif name == "get_task":
        return await handle_get_task(arguments)
    elif name == "delete_task":
        return await handle_delete_task(arguments)
    elif name == "transcribe_audio":
        return await handle_transcribe_audio(arguments)
    elif name == "fetch_page":
        return await handle_fetch_page(arguments)
    elif name == "create_scheduled_job":
        return await handle_create_scheduled_job(arguments)
    elif name == "list_scheduled_jobs":
        return await handle_list_scheduled_jobs(arguments)
    elif name == "get_scheduled_job":
        return await handle_get_scheduled_job(arguments)
    elif name == "update_scheduled_job":
        return await handle_update_scheduled_job(arguments)
    elif name == "delete_scheduled_job":
        return await handle_delete_scheduled_job(arguments)
    elif name == "check_task_outputs":
        return await handle_check_task_outputs(arguments)
    elif name == "write_task_output":
        return await handle_write_task_output(arguments)
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


# =============================================================================
# Core Message Handlers
# =============================================================================

async def handle_wait_for_messages(args: dict) -> list[TextContent]:
    """Block until new messages arrive in inbox, or return immediately if messages exist."""
    timeout = args.get("timeout", 300)

    touch_heartbeat()

    # Check if messages already exist
    existing = list(INBOX_DIR.glob("*.json"))
    if existing:
        touch_heartbeat()
        return await handle_check_inbox({"limit": 10})

    # No messages - set up inotify watcher and wait
    message_arrived = threading.Event()

    class InboxHandler(FileSystemEventHandler):
        def on_created(self, event):
            if not event.is_directory and event.src_path.endswith('.json'):
                message_arrived.set()

    observer = Observer()
    observer.schedule(InboxHandler(), str(INBOX_DIR), recursive=False)
    observer.start()

    try:
        heartbeat_interval = 60
        elapsed = 0

        while elapsed < timeout:
            wait_time = min(heartbeat_interval, timeout - elapsed)

            arrived = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda wt=wait_time: message_arrived.wait(timeout=wt)
            )

            if arrived:
                break

            touch_heartbeat()
            elapsed += wait_time

        if message_arrived.is_set():
            await asyncio.sleep(0.1)
            touch_heartbeat()
            return await handle_check_inbox({"limit": 10})
        else:
            touch_heartbeat()
            return [TextContent(
                type="text",
                text=f"No messages received in the last {timeout} seconds. Call `wait_for_messages` again to continue waiting."
            )]
    finally:
        observer.stop()
        observer.join(timeout=1)


async def handle_check_inbox(args: dict) -> list[TextContent]:
    """Check for new messages in inbox."""
    source_filter = args.get("source", "").lower()
    limit = args.get("limit", 10)

    messages = []
    for f in sorted(INBOX_DIR.glob("*.json")):
        try:
            with open(f) as fp:
                msg = json.load(fp)
                if source_filter and msg.get("source", "").lower() != source_filter:
                    continue
                msg["_filename"] = f.name
                messages.append(msg)
                if len(messages) >= limit:
                    break
        except Exception:
            continue

    if not messages:
        return [TextContent(type="text", text="No new messages in inbox.")]

    output = f"**{len(messages)} new message(s):**\n\n"
    for msg in messages:
        source = msg.get("source", "unknown").upper()
        user = msg.get("user_name", msg.get("username", "Unknown"))
        text = msg.get("text", "(no text)")
        ts = msg.get("timestamp", "")
        msg_id = msg.get("id", msg.get("_filename", ""))
        chat_id = msg.get("chat_id", "")
        msg_type = msg.get("type", "text")

        output += f"---\n"
        if msg_type == "voice":
            output += f"**[{source}]** (voice) from **{user}**\n"
            if not msg.get("transcription"):
                output += f"Voice message needs transcription - use `transcribe_audio`\n"
        else:
            output += f"**[{source}]** from **{user}**\n"
        output += f"Chat ID: `{chat_id}` | Message ID: `{msg_id}`\n"
        output += f"Time: {ts}\n\n"
        output += f"> {text}\n\n"

    output += "---\n"
    output += "Use `send_reply` to respond, `mark_processed` when done."

    return [TextContent(type="text", text=output)]


async def handle_send_reply(args: dict) -> list[TextContent]:
    """Send a reply to a message."""
    chat_id = args.get("chat_id")
    text = args.get("text", "")
    source = args.get("source", "telegram").lower()
    buttons = args.get("buttons")
    thread_ts = args.get("thread_ts")

    if not chat_id or not text:
        return [TextContent(type="text", text="Error: chat_id and text are required.")]

    reply_id = f"{int(time.time() * 1000)}_{source}"
    reply_data = {
        "id": reply_id,
        "source": source,
        "chat_id": chat_id,
        "text": text,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        # Agent persona info for Slack gateway
        "agent_name": AGENT_DISPLAY_NAME,
        "agent_icon": AGENT_CONFIG.get("icon_url", ""),
    }

    # Include buttons if provided (Telegram only)
    if buttons and source.startswith("telegram"):
        reply_data["buttons"] = buttons

    # Include thread_ts if provided (Slack only)
    if thread_ts and source == "slack":
        reply_data["thread_ts"] = thread_ts

    outbox_file = OUTBOX_DIR / f"{reply_id}.json"
    with open(outbox_file, "w") as f:
        json.dump(reply_data, f, indent=2)

    # Save a copy to sent directory for conversation history
    sent_file = SENT_DIR / f"{reply_id}.json"
    with open(sent_file, "w") as f:
        json.dump(reply_data, f, indent=2)

    button_info = f" with {sum(len(row) for row in buttons)} button(s)" if buttons else ""
    thread_info = f" (thread reply)" if thread_ts and source == "slack" else ""
    return [TextContent(type="text", text=f"Reply queued for {source} (chat {chat_id}){button_info}{thread_info}:\n\n{text[:100]}{'...' if len(text) > 100 else ''}")]


async def handle_mark_processed(args: dict) -> list[TextContent]:
    """Mark a message as processed."""
    message_id = args.get("message_id", "")

    if not message_id:
        return [TextContent(type="text", text="Error: message_id is required.")]

    found = None
    for f in INBOX_DIR.glob("*.json"):
        if message_id in f.name:
            found = f
            break
        try:
            with open(f) as fp:
                msg = json.load(fp)
                if msg.get("id") == message_id:
                    found = f
                    break
        except:
            continue

    if not found:
        return [TextContent(type="text", text=f"Message not found: {message_id}")]

    dest = PROCESSED_DIR / found.name
    found.rename(dest)

    return [TextContent(type="text", text=f"Message marked as processed: {message_id}")]


async def handle_list_sources(args: dict) -> list[TextContent]:
    """List available message sources."""
    output = f"**Message Sources ({AGENT_DISPLAY_NAME}):**\n\n"
    for key, source in SOURCES.items():
        status = "Enabled" if source["enabled"] else "Disabled"
        output += f"- **{source['name']}** ({key}): {status}\n"
    return [TextContent(type="text", text=output)]


async def handle_get_stats(args: dict) -> list[TextContent]:
    """Get inbox statistics."""
    inbox_count = len(list(INBOX_DIR.glob("*.json")))
    outbox_count = len(list(OUTBOX_DIR.glob("*.json")))
    processed_count = len(list(PROCESSED_DIR.glob("*.json")))

    source_counts = {}
    for f in INBOX_DIR.glob("*.json"):
        try:
            with open(f) as fp:
                msg = json.load(fp)
                src = msg.get("source", "unknown")
                source_counts[src] = source_counts.get(src, 0) + 1
        except:
            continue

    output = f"**Inbox Statistics ({AGENT_DISPLAY_NAME}):**\n\n"
    output += f"- Inbox: {inbox_count} messages\n"
    output += f"- Outbox: {outbox_count} pending replies\n"
    output += f"- Processed: {processed_count} total\n\n"

    if source_counts:
        output += "**By Source:**\n"
        for src, count in source_counts.items():
            output += f"- {src}: {count}\n"

    return [TextContent(type="text", text=output)]


# =============================================================================
# Conversation History Handler
# =============================================================================

async def handle_get_conversation_history(args: dict) -> list[TextContent]:
    """Retrieve past messages from conversation history."""
    chat_id_filter = args.get("chat_id")
    search_text = args.get("search", "").lower().strip()
    limit = min(args.get("limit", 20), 100)
    offset = args.get("offset", 0)
    direction = args.get("direction", "all").lower()
    source_filter = args.get("source", "").lower().strip()

    all_messages = []

    if direction in ("all", "received"):
        for f in PROCESSED_DIR.glob("*.json"):
            try:
                with open(f) as fp:
                    msg = json.load(fp)
                msg["_direction"] = "received"
                msg["_filename"] = f.name
                all_messages.append(msg)
            except Exception:
                continue

    if direction in ("all", "sent"):
        for f in SENT_DIR.glob("*.json"):
            try:
                with open(f) as fp:
                    msg = json.load(fp)
                msg["_direction"] = "sent"
                msg["_filename"] = f.name
                all_messages.append(msg)
            except Exception:
                continue

    if chat_id_filter is not None:
        chat_id_str = str(chat_id_filter)
        all_messages = [m for m in all_messages if str(m.get("chat_id", "")) == chat_id_str]

    if source_filter:
        all_messages = [m for m in all_messages if m.get("source", "").lower() == source_filter]

    if search_text:
        all_messages = [m for m in all_messages if search_text in m.get("text", "").lower()]

    def parse_timestamp(msg):
        ts = msg.get("timestamp", "")
        try:
            if "+" in ts or ts.endswith("Z"):
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return datetime.min.replace(tzinfo=timezone.utc)

    all_messages.sort(key=parse_timestamp, reverse=True)

    total_count = len(all_messages)
    paginated = all_messages[offset:offset + limit]

    if not paginated:
        filter_info = []
        if chat_id_filter is not None:
            filter_info.append(f"chat_id={chat_id_filter}")
        if search_text:
            filter_info.append(f"search='{search_text}'")
        if direction != "all":
            filter_info.append(f"direction={direction}")
        if source_filter:
            filter_info.append(f"source={source_filter}")
        filter_str = f" (filters: {', '.join(filter_info)})" if filter_info else ""
        return [TextContent(type="text", text=f"No messages found{filter_str}.")]

    showing_end = min(offset + limit, total_count)
    output = f"**Conversation History** (showing {offset + 1}-{showing_end} of {total_count}):\n\n"

    for msg in paginated:
        direction_label = "RECEIVED" if msg["_direction"] == "received" else "SENT"
        source = msg.get("source", "unknown").upper()
        chat_id = msg.get("chat_id", "")
        ts = msg.get("timestamp", "")
        text = msg.get("text", "(no text)")

        try:
            if "+" in ts or ts.endswith("Z"):
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(ts)
            ts_display = dt.strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            ts_display = ts

        if msg["_direction"] == "received":
            user = msg.get("user_name", msg.get("username", "Unknown"))
            output += f"---\n"
            output += f"**{direction_label}** [{source}] from **{user}** | Chat: `{chat_id}`\n"
            output += f"Time: {ts_display}\n\n"
            output += f"> {text[:500]}{'...' if len(text) > 500 else ''}\n\n"
        else:
            output += f"---\n"
            output += f"**{direction_label}** [{source}] to chat `{chat_id}`\n"
            output += f"Time: {ts_display}\n\n"
            output += f"> {text[:500]}{'...' if len(text) > 500 else ''}\n\n"

    if total_count > offset + limit:
        next_offset = offset + limit
        output += f"---\n*More messages available. Use `offset={next_offset}` to see the next page.*\n"

    return [TextContent(type="text", text=output)]


# =============================================================================
# Task Management Handlers
# =============================================================================

def load_tasks() -> dict:
    try:
        with open(TASKS_FILE, "r") as f:
            return json.load(f)
    except:
        return {"tasks": [], "next_id": 1}


def save_tasks(data: dict) -> None:
    with open(TASKS_FILE, "w") as f:
        json.dump(data, f, indent=2)


async def handle_list_tasks(args: dict) -> list[TextContent]:
    status_filter = args.get("status", "all").lower()
    data = load_tasks()
    tasks = data.get("tasks", [])

    if status_filter != "all":
        tasks = [t for t in tasks if t.get("status", "").lower() == status_filter]

    if not tasks:
        return [TextContent(type="text", text="No tasks found.")]

    pending = [t for t in tasks if t.get("status") == "pending"]
    in_progress = [t for t in tasks if t.get("status") == "in_progress"]
    completed = [t for t in tasks if t.get("status") == "completed"]

    output = "**Tasks:**\n\n"

    if in_progress:
        output += "**In Progress:**\n"
        for t in in_progress:
            output += f"  #{t['id']} {t['subject']}\n"
        output += "\n"

    if pending:
        output += "**Pending:**\n"
        for t in pending:
            output += f"  #{t['id']} {t['subject']}\n"
        output += "\n"

    if completed:
        output += "**Completed:**\n"
        for t in completed:
            output += f"  #{t['id']} {t['subject']}\n"
        output += "\n"

    output += f"---\nTotal: {len(tasks)} task(s)"
    return [TextContent(type="text", text=output)]


async def handle_create_task(args: dict) -> list[TextContent]:
    subject = args.get("subject", "").strip()
    description = args.get("description", "").strip()

    if not subject:
        return [TextContent(type="text", text="Error: subject is required.")]

    data = load_tasks()
    task_id = data.get("next_id", 1)

    task = {
        "id": task_id,
        "subject": subject,
        "description": description,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    data["tasks"].append(task)
    data["next_id"] = task_id + 1
    save_tasks(data)

    return [TextContent(type="text", text=f"Task #{task_id} created: {subject}")]


async def handle_update_task(args: dict) -> list[TextContent]:
    task_id = args.get("task_id")
    if task_id is None:
        return [TextContent(type="text", text="Error: task_id is required.")]

    data = load_tasks()
    task = None
    for t in data["tasks"]:
        if t["id"] == task_id:
            task = t
            break

    if not task:
        return [TextContent(type="text", text=f"Error: Task #{task_id} not found.")]

    if "status" in args:
        status = args["status"].lower()
        if status in ["pending", "in_progress", "completed"]:
            task["status"] = status
        else:
            return [TextContent(type="text", text=f"Error: Invalid status '{status}'. Use: pending, in_progress, completed")]

    if "subject" in args:
        task["subject"] = args["subject"]
    if "description" in args:
        task["description"] = args["description"]

    task["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_tasks(data)

    return [TextContent(type="text", text=f"Task #{task_id} updated: {task['subject']} [{task['status']}]")]


async def handle_get_task(args: dict) -> list[TextContent]:
    task_id = args.get("task_id")
    if task_id is None:
        return [TextContent(type="text", text="Error: task_id is required.")]

    data = load_tasks()
    task = None
    for t in data["tasks"]:
        if t["id"] == task_id:
            task = t
            break

    if not task:
        return [TextContent(type="text", text=f"Error: Task #{task_id} not found.")]

    output = f"**Task #{task['id']}**\n\n"
    output += f"**Subject:** {task['subject']}\n"
    output += f"**Status:** {task['status']}\n"
    if task.get("description"):
        output += f"\n**Description:**\n{task['description']}\n"
    output += f"\n**Created:** {task.get('created_at', 'N/A')}\n"
    output += f"**Updated:** {task.get('updated_at', 'N/A')}\n"

    return [TextContent(type="text", text=output)]


async def handle_delete_task(args: dict) -> list[TextContent]:
    task_id = args.get("task_id")
    if task_id is None:
        return [TextContent(type="text", text="Error: task_id is required.")]

    data = load_tasks()
    original_len = len(data["tasks"])
    data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]

    if len(data["tasks"]) == original_len:
        return [TextContent(type="text", text=f"Error: Task #{task_id} not found.")]

    save_tasks(data)
    return [TextContent(type="text", text=f"Task #{task_id} deleted.")]


# =============================================================================
# Audio Transcription Handler (Local Whisper.cpp)
# =============================================================================

FFMPEG_PATH = Path.home() / ".local" / "bin" / "ffmpeg"
WHISPER_CPP_PATH = Path.home() / "lobster-workspace" / "whisper.cpp" / "build" / "bin" / "whisper-cli"
WHISPER_MODEL_PATH = Path.home() / "lobster-workspace" / "whisper.cpp" / "models" / "ggml-small.bin"


async def convert_ogg_to_wav(ogg_path: Path, wav_path: Path) -> bool:
    ffmpeg = str(FFMPEG_PATH) if FFMPEG_PATH.exists() else "ffmpeg"
    cmd = [ffmpeg, "-i", str(ogg_path), "-ar", "16000", "-ac", "1", "-y", str(wav_path)]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, stderr = await proc.communicate()
    return proc.returncode == 0


async def run_whisper_cpp(audio_path: Path) -> tuple[bool, str]:
    if not WHISPER_CPP_PATH.exists():
        return False, f"whisper.cpp not found at {WHISPER_CPP_PATH}"
    if not WHISPER_MODEL_PATH.exists():
        return False, f"Whisper model not found at {WHISPER_MODEL_PATH}"

    cmd = [str(WHISPER_CPP_PATH), "-m", str(WHISPER_MODEL_PATH), "-f", str(audio_path), "-l", "en", "-nt", "--no-prints"]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode().strip() if stderr else "Unknown error"
        return False, f"whisper.cpp failed: {error_msg}"

    transcription = stdout.decode().strip()
    lines = [line for line in transcription.split('\n') if not line.strip().startswith('[')]
    transcription = ' '.join(lines).strip()
    return True, transcription


async def handle_transcribe_audio(args: dict) -> list[TextContent]:
    message_id = args.get("message_id", "")
    if not message_id:
        return [TextContent(type="text", text="Error: message_id is required.")]

    msg_file = None
    msg_data = None
    for f in INBOX_DIR.glob("*.json"):
        if message_id in f.name:
            msg_file = f
            break
        try:
            with open(f) as fp:
                data = json.load(fp)
                if data.get("id") == message_id:
                    msg_file = f
                    msg_data = data
                    break
        except:
            continue

    if not msg_file:
        for f in PROCESSED_DIR.glob("*.json"):
            if message_id in f.name:
                msg_file = f
                break
            try:
                with open(f) as fp:
                    data = json.load(fp)
                    if data.get("id") == message_id:
                        msg_file = f
                        msg_data = data
                        break
            except:
                continue

    if not msg_file:
        return [TextContent(type="text", text=f"Error: Message not found: {message_id}")]

    if not msg_data:
        with open(msg_file) as fp:
            msg_data = json.load(fp)

    if msg_data.get("type") != "voice":
        return [TextContent(type="text", text=f"Error: Message {message_id} is not a voice message.")]

    if msg_data.get("transcription"):
        return [TextContent(type="text", text=f"Already transcribed:\n\n{msg_data['transcription']}")]

    audio_path = Path(msg_data.get("audio_file", ""))
    if not audio_path.exists():
        return [TextContent(type="text", text=f"Error: Audio file not found: {audio_path}")]

    try:
        if audio_path.suffix.lower() in [".ogg", ".oga", ".opus"]:
            wav_path = audio_path.with_suffix(".wav")
            if not wav_path.exists():
                success = await convert_ogg_to_wav(audio_path, wav_path)
                if not success:
                    return [TextContent(type="text", text="Error: Failed to convert audio to WAV format.")]
            transcribe_path = wav_path
        else:
            transcribe_path = audio_path

        success, result = await run_whisper_cpp(transcribe_path)
        if not success:
            return [TextContent(type="text", text=f"Error: {result}")]

        transcription = result
        if not transcription:
            return [TextContent(type="text", text="Error: Empty transcription returned.")]

        msg_data["transcription"] = transcription
        msg_data["text"] = transcription
        msg_data["transcribed_at"] = datetime.now(timezone.utc).isoformat()
        msg_data["transcription_model"] = "whisper.cpp-small"

        with open(msg_file, "w") as fp:
            json.dump(msg_data, fp, indent=2)

        return [TextContent(type="text", text=f"**Transcription complete (whisper.cpp small):**\n\n{transcription}")]

    except Exception as e:
        return [TextContent(type="text", text=f"Error during transcription: {str(e)}")]


# =============================================================================
# Headless Browser Fetch Handler
# =============================================================================

async def handle_fetch_page(args: dict) -> list[TextContent]:
    url = args.get("url", "").strip()
    wait_seconds = args.get("wait_seconds", 3)
    timeout_seconds = args.get("timeout", 30)

    if not url:
        return [TextContent(type="text", text="Error: url is required.")]

    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 900},
                java_script_enabled=True,
            )
            page = await context.new_page()

            timeout_ms = timeout_seconds * 1000
            try:
                response = await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            except Exception as nav_err:
                await browser.close()
                return [TextContent(type="text", text=f"Error navigating to {url}: {str(nav_err)}")]

            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)

            try:
                await page.wait_for_load_state("networkidle", timeout=min(10000, timeout_ms // 2))
            except Exception:
                pass

            final_url = page.url
            title = await page.title()
            text_content = ""

            # Twitter/X strategy
            if "twitter.com" in url or "x.com" in url:
                try:
                    await page.wait_for_selector('[data-testid="tweetText"]', timeout=8000)
                    tweet_elements = await page.query_selector_all('[data-testid="tweetText"]')
                    tweet_texts = []
                    for el in tweet_elements:
                        t = await el.inner_text()
                        if t.strip():
                            tweet_texts.append(t.strip())

                    author_elements = await page.query_selector_all('[data-testid="User-Name"]')
                    authors = []
                    for el in author_elements:
                        a = await el.inner_text()
                        if a.strip():
                            authors.append(a.strip())

                    if tweet_texts:
                        parts = []
                        for i, tweet in enumerate(tweet_texts[:10]):
                            author = authors[i] if i < len(authors) else ""
                            if author:
                                parts.append(f"{author}\n{tweet}")
                            else:
                                parts.append(tweet)
                        text_content = "\n\n---\n\n".join(parts)
                except Exception:
                    pass

            # Article strategy
            if not text_content:
                try:
                    for selector in ["article", "main", '[role="main"]', ".post-content", ".article-body", ".entry-content"]:
                        el = await page.query_selector(selector)
                        if el:
                            candidate = await el.inner_text()
                            if len(candidate.strip()) > len(text_content):
                                text_content = candidate.strip()
                except Exception:
                    pass

            # Fallback to body
            if not text_content or len(text_content) < 50:
                try:
                    text_content = await page.inner_text("body")
                except Exception:
                    text_content = ""

            status_code = response.status if response else "unknown"
            await browser.close()

            if text_content:
                text_content = re.sub(r'\n{3,}', '\n\n', text_content).strip()
                max_len = 15000
                if len(text_content) > max_len:
                    text_content = text_content[:max_len] + f"\n\n... (truncated, {len(text_content)} total chars)"

            if not text_content:
                return [TextContent(type="text", text=f"Page loaded but no text content extracted.\n\nURL: {final_url}\nStatus: {status_code}\nTitle: {title}")]

            header = f"**{title}**\nURL: {final_url}\nStatus: {status_code}\n\n---\n\n"
            return [TextContent(type="text", text=header + text_content)]

    except ImportError:
        return [TextContent(type="text", text="Error: Playwright is not installed. Run: pip install playwright && python -m playwright install chromium")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error fetching page: {str(e)}")]


# =============================================================================
# Scheduled Jobs Handlers
# =============================================================================

def load_scheduled_jobs() -> dict:
    try:
        with open(SCHEDULED_JOBS_FILE, "r") as f:
            return json.load(f)
    except:
        return {"jobs": {}}


def save_scheduled_jobs(data: dict) -> None:
    with open(SCHEDULED_JOBS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def validate_cron_schedule(schedule: str) -> tuple[bool, str]:
    parts = schedule.strip().split()
    if len(parts) != 5:
        return False, f"Cron schedule must have 5 parts (minute hour day month weekday), got {len(parts)}"

    field_names = ["minute", "hour", "day", "month", "weekday"]
    field_ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]

    for i, (part, fname, (min_val, max_val)) in enumerate(zip(parts, field_names, field_ranges)):
        if part == "*":
            continue
        if part.startswith("*/"):
            try:
                step = int(part[2:])
                if step < 1:
                    return False, f"Invalid step value in {fname}: {part}"
            except ValueError:
                return False, f"Invalid step value in {fname}: {part}"
            continue

        for subpart in part.split(","):
            if "-" in subpart:
                try:
                    start, end = subpart.split("-")
                    start, end = int(start), int(end)
                    if not (min_val <= start <= max_val and min_val <= end <= max_val):
                        return False, f"Range out of bounds in {fname}: {subpart}"
                except ValueError:
                    return False, f"Invalid range in {fname}: {subpart}"
            else:
                try:
                    val = int(subpart)
                    if not (min_val <= val <= max_val):
                        return False, f"Value out of range in {fname}: {val} (must be {min_val}-{max_val})"
                except ValueError:
                    return False, f"Invalid value in {fname}: {subpart}"

    return True, ""


def cron_to_human(schedule: str) -> str:
    parts = schedule.strip().split()
    if len(parts) != 5:
        return schedule

    minute, hour, day, month, weekday = parts

    if schedule == "* * * * *":
        return "Every minute"
    if minute.startswith("*/"):
        mins = minute[2:]
        if hour == "*" and day == "*" and month == "*" and weekday == "*":
            return f"Every {mins} minutes"
    if hour.startswith("*/"):
        hrs = hour[2:]
        if minute == "0" and day == "*" and month == "*" and weekday == "*":
            return f"Every {hrs} hours"
    if day == "*" and month == "*" and weekday == "*":
        if minute != "*" and hour != "*":
            return f"Daily at {hour}:{minute.zfill(2)}"
    if weekday != "*" and day == "*" and month == "*":
        days = {"0": "Sun", "1": "Mon", "2": "Tue", "3": "Wed", "4": "Thu", "5": "Fri", "6": "Sat", "7": "Sun"}
        day_name = days.get(weekday, weekday)
        if minute != "*" and hour != "*":
            return f"Every {day_name} at {hour}:{minute.zfill(2)}"

    return schedule


def validate_job_name(name: str) -> tuple[bool, str]:
    if not name:
        return False, "Job name cannot be empty"
    if not re.match(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$', name):
        return False, "Job name must be lowercase alphanumeric with hyphens, cannot start/end with hyphen"
    if len(name) > 50:
        return False, "Job name must be 50 characters or less"
    return True, ""


def sync_crontab() -> tuple[bool, str]:
    sync_script = SCHEDULED_TASKS_DIR / "sync-crontab.sh"
    try:
        result = subprocess.run([str(sync_script)], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return True, result.stdout
        else:
            return False, result.stderr or "Sync failed"
    except subprocess.TimeoutExpired:
        return False, "Sync script timed out"
    except Exception as e:
        return False, str(e)


async def handle_create_scheduled_job(args: dict) -> list[TextContent]:
    name = args.get("name", "").strip().lower()
    schedule = args.get("schedule", "").strip()
    context = args.get("context", "").strip()

    valid, error = validate_job_name(name)
    if not valid:
        return [TextContent(type="text", text=f"Error: {error}")]

    valid, error = validate_cron_schedule(schedule)
    if not valid:
        return [TextContent(type="text", text=f"Error: Invalid cron schedule - {error}")]

    if not context:
        return [TextContent(type="text", text="Error: context is required")]

    data = load_scheduled_jobs()
    if name in data.get("jobs", {}):
        return [TextContent(type="text", text=f"Error: Job '{name}' already exists. Use update_scheduled_job to modify it.")]

    now = datetime.now(timezone.utc)
    task_file = SCHEDULED_TASKS_TASKS_DIR / f"{name}.md"
    schedule_human = cron_to_human(schedule)

    task_content = f"""# {name.replace('-', ' ').title()}

**Job**: {name}
**Schedule**: {schedule_human} (`{schedule}`)
**Created**: {now.strftime('%Y-%m-%d %H:%M UTC')}

## Context

You are running as a scheduled task. The {AGENT_DISPLAY_NAME} instance created this job.

## Instructions

{context}

## Output

When you complete your task, call `write_task_output` with:
- job_name: "{name}"
- output: Your results/summary
- status: "success" or "failed"

Keep output concise. The {AGENT_DISPLAY_NAME} instance will review this later.
"""

    task_file.write_text(task_content)

    data["jobs"][name] = {
        "name": name,
        "schedule": schedule,
        "schedule_human": schedule_human,
        "task_file": f"tasks/{name}.md",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "enabled": True,
        "last_run": None,
        "last_status": None,
    }
    save_scheduled_jobs(data)

    success, msg = sync_crontab()
    if not success:
        return [TextContent(type="text", text=f"Job created but crontab sync failed: {msg}")]

    return [TextContent(type="text", text=f"Created scheduled job '{name}'\nSchedule: {schedule_human} (`{schedule}`)\nTask file: {task_file}")]


async def handle_list_scheduled_jobs(args: dict) -> list[TextContent]:
    data = load_scheduled_jobs()
    jobs = data.get("jobs", {})

    if not jobs:
        return [TextContent(type="text", text="No scheduled jobs configured.\n\nUse `create_scheduled_job` to create one.")]

    output = "**Scheduled Jobs:**\n\n"
    for name, job in sorted(jobs.items()):
        status_icon = "" if job.get("enabled", True) else " (disabled)"
        schedule = job.get("schedule_human", job.get("schedule", ""))
        last_run = job.get("last_run", "never")
        last_status = job.get("last_status", "-")

        if last_run and last_run != "never":
            try:
                dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
                last_run = dt.strftime("%Y-%m-%d %H:%M")
            except:
                pass

        output += f"**{name}**{status_icon}\n"
        output += f"  Schedule: {schedule}\n"
        output += f"  Last run: {last_run} ({last_status})\n\n"

    output += f"---\nTotal: {len(jobs)} job(s)"
    return [TextContent(type="text", text=output)]


async def handle_get_scheduled_job(args: dict) -> list[TextContent]:
    name = args.get("name", "").strip().lower()
    if not name:
        return [TextContent(type="text", text="Error: name is required")]

    data = load_scheduled_jobs()
    job = data.get("jobs", {}).get(name)
    if not job:
        return [TextContent(type="text", text=f"Error: Job '{name}' not found")]

    task_file = SCHEDULED_TASKS_TASKS_DIR / f"{name}.md"
    task_content = ""
    if task_file.exists():
        task_content = task_file.read_text()

    output = f"**Job: {name}**\n\n"
    output += f"**Schedule**: {job.get('schedule_human', '')} (`{job.get('schedule', '')}`)\n"
    output += f"**Enabled**: {'Yes' if job.get('enabled', True) else 'No'}\n"
    output += f"**Created**: {job.get('created_at', 'N/A')}\n"
    output += f"**Updated**: {job.get('updated_at', 'N/A')}\n"
    output += f"**Last Run**: {job.get('last_run', 'never')}\n"
    output += f"**Last Status**: {job.get('last_status', '-')}\n\n"
    output += f"---\n\n**Task File** (`{task_file}`):\n\n```markdown\n{task_content}\n```"

    return [TextContent(type="text", text=output)]


async def handle_update_scheduled_job(args: dict) -> list[TextContent]:
    name = args.get("name", "").strip().lower()
    if not name:
        return [TextContent(type="text", text="Error: name is required")]

    data = load_scheduled_jobs()
    job = data.get("jobs", {}).get(name)
    if not job:
        return [TextContent(type="text", text=f"Error: Job '{name}' not found")]

    updated = []

    if "schedule" in args and args["schedule"]:
        new_schedule = args["schedule"].strip()
        valid, error = validate_cron_schedule(new_schedule)
        if not valid:
            return [TextContent(type="text", text=f"Error: Invalid cron schedule - {error}")]
        job["schedule"] = new_schedule
        job["schedule_human"] = cron_to_human(new_schedule)
        updated.append(f"schedule -> {new_schedule}")

    if "enabled" in args:
        job["enabled"] = bool(args["enabled"])
        updated.append(f"enabled -> {job['enabled']}")

    if "context" in args and args["context"]:
        new_context = args["context"].strip()
        task_file = SCHEDULED_TASKS_TASKS_DIR / f"{name}.md"
        now = datetime.now(timezone.utc)
        task_content = f"""# {name.replace('-', ' ').title()}

**Job**: {name}
**Schedule**: {job.get('schedule_human', '')} (`{job.get('schedule', '')}`)
**Created**: {job.get('created_at', 'N/A')}
**Updated**: {now.strftime('%Y-%m-%d %H:%M UTC')}

## Context

You are running as a scheduled task. The {AGENT_DISPLAY_NAME} instance created this job.

## Instructions

{new_context}

## Output

When you complete your task, call `write_task_output` with:
- job_name: "{name}"
- output: Your results/summary
- status: "success" or "failed"

Keep output concise. The {AGENT_DISPLAY_NAME} instance will review this later.
"""
        task_file.write_text(task_content)
        updated.append("context (task file rewritten)")

    if not updated:
        return [TextContent(type="text", text="No changes specified. Provide schedule, context, or enabled.")]

    job["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_scheduled_jobs(data)

    success, msg = sync_crontab()
    sync_status = "" if success else f"\n(Warning: crontab sync failed: {msg})"

    return [TextContent(type="text", text=f"Updated job '{name}':\n- " + "\n- ".join(updated) + sync_status)]


async def handle_delete_scheduled_job(args: dict) -> list[TextContent]:
    name = args.get("name", "").strip().lower()
    if not name:
        return [TextContent(type="text", text="Error: name is required")]

    data = load_scheduled_jobs()
    if name not in data.get("jobs", {}):
        return [TextContent(type="text", text=f"Error: Job '{name}' not found")]

    del data["jobs"][name]
    save_scheduled_jobs(data)

    task_file = SCHEDULED_TASKS_TASKS_DIR / f"{name}.md"
    if task_file.exists():
        task_file.unlink()

    success, msg = sync_crontab()
    sync_status = "" if success else f"\n(Warning: crontab sync failed: {msg})"

    return [TextContent(type="text", text=f"Deleted job '{name}'" + sync_status)]


async def handle_check_task_outputs(args: dict) -> list[TextContent]:
    since = args.get("since")
    limit = args.get("limit", 10)
    job_name_filter = args.get("job_name", "").strip().lower()

    output_files = sorted(TASK_OUTPUTS_DIR.glob("*.json"), reverse=True)

    if not output_files:
        return [TextContent(type="text", text="No task outputs yet.\n\nOutputs will appear here when scheduled jobs complete.")]

    outputs = []
    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except:
            pass

    for f in output_files:
        if len(outputs) >= limit:
            break
        try:
            with open(f) as fp:
                data = json.load(fp)
            if job_name_filter and data.get("job_name", "").lower() != job_name_filter:
                continue
            if since_dt:
                try:
                    output_dt = datetime.fromisoformat(data.get("timestamp", "").replace("Z", "+00:00"))
                    if output_dt < since_dt:
                        continue
                except:
                    pass
            data["_filename"] = f.name
            outputs.append(data)
        except Exception:
            continue

    if not outputs:
        filter_msg = ""
        if job_name_filter:
            filter_msg = f" for job '{job_name_filter}'"
        if since:
            filter_msg += f" since {since}"
        return [TextContent(type="text", text=f"No task outputs found{filter_msg}.")]

    result = f"**Recent Task Outputs** ({len(outputs)}):\n\n"
    for out in outputs:
        job = out.get("job_name", "unknown")
        ts = out.get("timestamp", "")
        status = out.get("status", "unknown")
        output = out.get("output", "(no output)")
        duration = out.get("duration_seconds")
        duration_str = f" ({duration}s)" if duration else ""

        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            ts = dt.strftime("%Y-%m-%d %H:%M")
        except:
            pass

        result += f"---\n"
        result += f"**{job}** [{status}] {ts}{duration_str}\n\n"
        result += f"> {output[:500]}{'...' if len(output) > 500 else ''}\n\n"

    return [TextContent(type="text", text=result)]


async def handle_write_task_output(args: dict) -> list[TextContent]:
    job_name = args.get("job_name", "").strip().lower()
    output = args.get("output", "").strip()
    status = args.get("status", "success").lower()

    if not job_name:
        return [TextContent(type="text", text="Error: job_name is required")]
    if not output:
        return [TextContent(type="text", text="Error: output is required")]

    if status not in ["success", "failed"]:
        status = "success"

    now = datetime.now(timezone.utc)
    timestamp_str = now.strftime("%Y%m%d-%H%M%S")

    output_data = {
        "job_name": job_name,
        "timestamp": now.isoformat(),
        "status": status,
        "output": output,
    }

    output_file = TASK_OUTPUTS_DIR / f"{timestamp_str}-{job_name}.json"
    with open(output_file, "w") as f:
        json.dump(output_data, f, indent=2)

    return [TextContent(type="text", text=f"Output recorded for job '{job_name}'")]


# =============================================================================
# Main
# =============================================================================

async def run_main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run_main())
