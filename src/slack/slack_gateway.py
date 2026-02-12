#!/usr/bin/env python3
"""
Multi-Agent Slack Gateway

Single gateway between Slack and all Potential agents.
Uses the Web API to poll for new messages and post replies with per-agent personas.

Architecture:
    Slack channels  -->  slack_gateway.py  -->  ~/messages/<agent>-inbox/
    Slack channels  <--  slack_gateway.py  <--  ~/messages/<agent>-outbox/

Key features:
    - Channel-based routing: each channel maps to a primary agent
    - chat:write.customize: single bot posts as different personas (username + icon_url)
    - Multi-outbox watching: watches all agent outboxes for source="slack" replies
    - Minimal resource usage: polling with backoff, no Socket Mode / no app-level token required

Usage:
    export SLACK_BOT_TOKEN=xoxb-...
    python slack_gateway.py

    Or source from slack.env:
    source ~/lobster/config/slack.env && python slack_gateway.py
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# =============================================================================
# Configuration
# =============================================================================

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
if not SLACK_BOT_TOKEN:
    raise ValueError("SLACK_BOT_TOKEN environment variable is required")

# Load agents config
AGENTS_CONFIG_PATH = Path.home() / "lobster" / "config" / "agents.json"

def load_agents_config() -> dict:
    try:
        return json.loads(AGENTS_CONFIG_PATH.read_text())
    except Exception as e:
        print(f"Warning: Could not load agents.json: {e}")
        return {}

AGENTS_CONFIG = load_agents_config()

# Load channel IDs from slack.env
SLACK_ENV_PATH = Path.home() / "lobster" / "config" / "slack.env"

def load_slack_channels() -> dict:
    """Parse slack.env for SLACK_CHANNEL_* variables -> {slug: channel_id}."""
    channels = {}
    if SLACK_ENV_PATH.exists():
        for line in SLACK_ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith("SLACK_CHANNEL_") and "=" in line:
                key, value = line.split("=", 1)
                # SLACK_CHANNEL_ENGINEERING -> engineering
                slug = key.replace("SLACK_CHANNEL_", "").lower().replace("_", "-")
                channels[slug] = value.strip()
    return channels

SLACK_CHANNELS = load_slack_channels()

# Build channel_id -> agent mapping from agents.json + slack.env
# Each channel maps to ONE primary agent (v1: simple, no multi-routing)
CHANNEL_AGENT_MAP = {}
for agent_name, config in AGENTS_CONFIG.items():
    for channel_slug in config.get("channels", []):
        channel_id = SLACK_CHANNELS.get(channel_slug)
        if channel_id and channel_id not in CHANNEL_AGENT_MAP:
            # First agent to claim a channel is the primary
            CHANNEL_AGENT_MAP[channel_id] = agent_name

# Directories
BASE_DIR = Path.home() / "messages"

# Collect all agent outboxes to watch
AGENT_OUTBOXES = {}
for agent_name, config in AGENTS_CONFIG.items():
    if config.get("telegram_only"):
        continue  # Skip agents that don't use Slack (e.g., Amber)
    if agent_name == "lobster":
        outbox = BASE_DIR / "outbox"
    else:
        outbox = BASE_DIR / f"{agent_name}-outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    AGENT_OUTBOXES[agent_name] = outbox

# Logging
LOG_DIR = Path.home() / "lobster-workspace" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "slack-gateway.log"),
    ],
)
log = logging.getLogger("slack-gateway")

# Initialize Slack client
client = WebClient(token=SLACK_BOT_TOKEN)

# Caches
user_cache = {}
channel_cache = {}

# Track last-seen timestamps per channel for polling
LAST_SEEN_FILE = BASE_DIR / "slack-gateway-state.json"

def load_state() -> dict:
    try:
        return json.loads(LAST_SEEN_FILE.read_text())
    except:
        return {"last_seen": {}}

def save_state(state: dict):
    LAST_SEEN_FILE.write_text(json.dumps(state, indent=2))


# =============================================================================
# Slack API Helpers
# =============================================================================

def get_user_info(user_id: str) -> dict:
    if user_id in user_cache:
        return user_cache[user_id]
    try:
        result = client.users_info(user=user_id)
        user_info = result.get("user", {})
        user_cache[user_id] = user_info
        return user_info
    except SlackApiError as e:
        log.warning(f"Error fetching user info for {user_id}: {e}")
        return {}


def get_channel_info(channel_id: str) -> dict:
    if channel_id in channel_cache:
        return channel_cache[channel_id]
    try:
        result = client.conversations_info(channel=channel_id)
        channel_info = result.get("channel", {})
        channel_cache[channel_id] = channel_info
        return channel_info
    except SlackApiError as e:
        log.warning(f"Error fetching channel info for {channel_id}: {e}")
        return {}


def clean_slack_text(text: str, bot_user_id: str = None) -> str:
    if not text:
        return ""
    if bot_user_id:
        text = re.sub(rf'<@{bot_user_id}>\s*', '', text)

    def replace_user_mention(match):
        uid = match.group(1)
        user_info = get_user_info(uid)
        display_name = user_info.get("profile", {}).get("display_name") or user_info.get("name", uid)
        return f"@{display_name}"

    text = re.sub(r'<@(U[A-Z0-9]+)>', replace_user_mention, text)
    text = re.sub(r'<#[A-Z0-9]+\|([^>]+)>', r'#\1', text)
    text = re.sub(r'<(https?://[^|>]+)\|[^>]+>', r'\1', text)
    text = re.sub(r'<(https?://[^>]+)>', r'\1', text)
    return text.strip()


# =============================================================================
# Bot Identity
# =============================================================================

try:
    auth_response = client.auth_test()
    BOT_USER_ID = auth_response.get("user_id")
    BOT_NAME = auth_response.get("user")
    log.info(f"Connected as bot: {BOT_NAME} ({BOT_USER_ID})")
except SlackApiError as e:
    log.error(f"Failed to get bot info: {e}")
    BOT_USER_ID = None
    BOT_NAME = None


# =============================================================================
# Inbound: Poll Slack channels for new messages
# =============================================================================

def get_agent_inbox(agent_name: str) -> Path:
    """Get inbox directory for an agent."""
    if agent_name == "lobster":
        inbox = BASE_DIR / "inbox"
    elif agent_name == "amber":
        inbox = BASE_DIR / "amber-inbox"
    else:
        inbox = BASE_DIR / f"{agent_name}-inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    return inbox


def write_message_to_inbox(inbox_dir: Path, msg_data: dict):
    """Write a message to an agent's inbox directory."""
    msg_id = msg_data.get("id", f"{int(time.time() * 1000)}_slack")
    inbox_file = inbox_dir / f"{msg_id}.json"
    with open(inbox_file, 'w') as f:
        json.dump(msg_data, f, indent=2)
    log.info(f"Wrote message to {inbox_dir.name}: {msg_id}")


def poll_channels():
    """Poll all monitored channels for new messages."""
    state = load_state()
    last_seen = state.get("last_seen", {})

    for channel_id, agent_name in CHANNEL_AGENT_MAP.items():
        try:
            kwargs = {
                "channel": channel_id,
                "limit": 20,
            }
            # Use oldest= to only get new messages since last seen
            if channel_id in last_seen:
                kwargs["oldest"] = last_seen[channel_id]

            result = client.conversations_history(**kwargs)
            messages = result.get("messages", [])

            if not messages:
                continue

            # Messages are newest-first; process oldest-first
            messages.reverse()

            newest_ts = last_seen.get(channel_id, "0")

            for msg in messages:
                ts = msg.get("ts", "")

                # Skip if we've already seen this message
                if ts <= last_seen.get(channel_id, "0"):
                    continue

                # Skip bot messages (including our own)
                if msg.get("bot_id") or msg.get("subtype") in ["bot_message", "channel_join", "channel_leave"]:
                    if ts > newest_ts:
                        newest_ts = ts
                    continue

                user_id = msg.get("user", "")
                text = msg.get("text", "")

                if not user_id or not text:
                    if ts > newest_ts:
                        newest_ts = ts
                    continue

                # Get user info
                user_info = get_user_info(user_id)
                channel_info = get_channel_info(channel_id)

                username = user_info.get("name", user_id)
                display_name = user_info.get("profile", {}).get("display_name") or user_info.get("real_name", username)
                channel_name = channel_info.get("name", channel_id)

                cleaned_text = clean_slack_text(text, BOT_USER_ID)
                thread_ts = msg.get("thread_ts")

                msg_id = f"{int(time.time() * 1000)}_{ts.replace('.', '')}"
                msg_data = {
                    "id": msg_id,
                    "source": "slack",
                    "chat_id": channel_id,
                    "user_id": user_id,
                    "username": username,
                    "user_name": display_name,
                    "text": cleaned_text,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "slack_ts": ts,
                    "channel_name": channel_name,
                    "is_dm": False,
                }

                if thread_ts:
                    msg_data["thread_ts"] = thread_ts

                inbox = get_agent_inbox(agent_name)
                write_message_to_inbox(inbox, msg_data)

                if ts > newest_ts:
                    newest_ts = ts

            # Update last seen for this channel
            if newest_ts > last_seen.get(channel_id, "0"):
                last_seen[channel_id] = newest_ts

        except SlackApiError as e:
            if "not_in_channel" in str(e):
                log.warning(f"Bot not in channel {channel_id}, attempting to join...")
                try:
                    client.conversations_join(channel=channel_id)
                    log.info(f"Joined channel {channel_id}")
                except SlackApiError as je:
                    log.error(f"Failed to join channel {channel_id}: {je}")
            else:
                log.error(f"Error polling channel {channel_id}: {e}")
        except Exception as e:
            log.error(f"Error polling channel {channel_id}: {e}")

    state["last_seen"] = last_seen
    save_state(state)


# =============================================================================
# Outbound: Watch agent outboxes for Slack replies
# =============================================================================

class OutboxHandler(FileSystemEventHandler):
    """Watches an agent outbox for reply files and sends them via Slack."""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name

    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith('.json'):
            Thread(target=self.process_reply_sync, args=(event.src_path,)).start()

    def process_reply_sync(self, filepath):
        try:
            time.sleep(0.2)  # Brief delay to ensure file is written
            with open(filepath, 'r') as f:
                reply = json.load(f)

            # Only process Slack replies
            if reply.get('source', '').lower() != 'slack':
                return

            channel_id = reply.get('chat_id')
            text = reply.get('text', '')
            thread_ts = reply.get('thread_ts')

            if not channel_id or not text:
                log.warning(f"Invalid Slack reply from {self.agent_name}: missing channel_id or text")
                os.remove(filepath)
                return

            kwargs = {
                "channel": channel_id,
                "text": text,
            }

            if thread_ts:
                kwargs["thread_ts"] = thread_ts

            # Multi-agent persona support via chat:write.customize
            agent_name = reply.get("agent_name")
            agent_icon = reply.get("agent_icon")
            if agent_name:
                kwargs["username"] = agent_name
            if agent_icon:
                kwargs["icon_url"] = agent_icon

            try:
                client.chat_postMessage(**kwargs)
                log.info(f"Sent Slack reply from {self.agent_name} to {channel_id}: {text[:50]}...")
            except SlackApiError as e:
                log.error(f"Error sending Slack message from {self.agent_name}: {e}")

            # Remove processed file
            os.remove(filepath)

        except Exception as e:
            log.error(f"Error processing reply from {self.agent_name} ({filepath}): {e}")


def process_existing_outboxes():
    """Process any existing Slack reply files on startup."""
    for agent_name, outbox_dir in AGENT_OUTBOXES.items():
        handler = OutboxHandler(agent_name)
        for filepath in outbox_dir.glob("*.json"):
            try:
                with open(filepath, 'r') as f:
                    reply = json.load(f)
                if reply.get('source', '').lower() == 'slack':
                    handler.process_reply_sync(str(filepath))
            except Exception as e:
                log.error(f"Error processing existing outbox file {filepath}: {e}")


# =============================================================================
# Main Loop
# =============================================================================

def main():
    log.info("=" * 60)
    log.info("Multi-Agent Slack Gateway starting...")
    log.info(f"Bot: {BOT_NAME} ({BOT_USER_ID})")
    log.info(f"Agents config: {AGENTS_CONFIG_PATH}")
    log.info(f"Channels file: {SLACK_ENV_PATH}")
    log.info("")

    # Log channel -> agent mapping
    for channel_id, agent_name in CHANNEL_AGENT_MAP.items():
        channel_info = get_channel_info(channel_id)
        channel_name = channel_info.get("name", channel_id)
        log.info(f"  #{channel_name} ({channel_id}) -> {agent_name}")
    log.info("")

    # Log outbox watchers
    for agent_name, outbox_dir in AGENT_OUTBOXES.items():
        log.info(f"  Watching outbox: {outbox_dir} ({agent_name})")
    log.info("=" * 60)

    # Join all monitored channels
    for channel_id in CHANNEL_AGENT_MAP.keys():
        try:
            client.conversations_join(channel=channel_id)
        except SlackApiError as e:
            if "already_in_channel" not in str(e):
                log.warning(f"Could not join channel {channel_id}: {e}")

    # Set up outbox watchers
    observer = Observer()
    for agent_name, outbox_dir in AGENT_OUTBOXES.items():
        observer.schedule(OutboxHandler(agent_name), str(outbox_dir), recursive=False)
    observer.start()
    log.info("Outbox watchers started")

    # Process any existing outbox files
    process_existing_outboxes()

    # Initialize polling state: set last_seen to "now" so we don't replay history
    state = load_state()
    if not state.get("last_seen"):
        now_ts = str(time.time())
        state["last_seen"] = {ch: now_ts for ch in CHANNEL_AGENT_MAP.keys()}
        save_state(state)
        log.info("Initialized polling state (starting from now)")

    # Polling loop
    poll_interval = 5  # seconds between polls (5s base)
    max_interval = 30  # max interval with backoff
    idle_count = 0

    try:
        log.info(f"Starting poll loop (interval: {poll_interval}s)...")
        while True:
            try:
                poll_channels()
            except Exception as e:
                log.error(f"Error in poll loop: {e}")

            # Simple backoff: if no new messages for a while, poll less frequently
            # (We always poll at least every 30s to stay responsive)
            time.sleep(min(poll_interval, max_interval))

    except KeyboardInterrupt:
        log.info("Shutting down...")
    finally:
        observer.stop()
        observer.join()
        log.info("Slack gateway stopped")


if __name__ == "__main__":
    main()
