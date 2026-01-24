#!/usr/bin/env python3
"""
Hyperion Daemon - Always-on Claude Code message processor

This daemon monitors the inbox and invokes Claude to process messages.
Each invocation is independent - context is provided via the CLAUDE.md file.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Configuration
INBOX_DIR = Path.home() / "messages" / "inbox"
WORKSPACE = Path.home() / "hyperion-workspace"
LOG_DIR = WORKSPACE / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "daemon.log"

POLL_INTERVAL = 5  # seconds between checks
IDLE_POLL_INTERVAL = 10  # seconds when no messages
CLAUDE_TIMEOUT = 300  # 5 minutes max per invocation

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE),
    ],
)
log = logging.getLogger("hyperion")


def count_inbox_messages() -> int:
    """Count messages in inbox."""
    return len(list(INBOX_DIR.glob("*.json")))


def get_inbox_messages() -> list[dict]:
    """Read all messages from inbox."""
    messages = []
    for f in sorted(INBOX_DIR.glob("*.json")):
        try:
            messages.append(json.loads(f.read_text()))
        except Exception as e:
            log.warning(f"Failed to read {f}: {e}")
    return messages


async def process_messages() -> tuple[bool, str]:
    """
    Invoke Claude to process inbox messages.
    Each invocation is independent - context comes from CLAUDE.md.
    """
    prompt = """You are Hyperion. Check your inbox and process all messages.

For each message:
1. Use check_inbox to see the messages
2. Read and understand what the user wants
3. Compose a helpful, concise response (users are on mobile)
4. Use send_reply with the correct chat_id
5. Use mark_processed to clear the message

Process ALL messages in the inbox."""

    cmd = [
        "claude",
        "-p", prompt,
        "--print",
        "--allowedTools", ",".join([
            "mcp__hyperion-inbox__check_inbox",
            "mcp__hyperion-inbox__send_reply",
            "mcp__hyperion-inbox__mark_processed",
            "mcp__hyperion-inbox__get_stats",
            "Read",
            "Write",
            "Bash",
        ]),
    ]

    log.info("Invoking Claude to process messages...")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=WORKSPACE,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=CLAUDE_TIMEOUT
        )

        output = stdout.decode().strip()
        errors = stderr.decode().strip()

        if proc.returncode != 0:
            log.error(f"Claude error (code {proc.returncode}): {errors}")
            return False, errors

        log.info(f"Claude completed: {output[:200]}...")
        return True, output

    except asyncio.TimeoutError:
        log.error(f"Claude timed out after {CLAUDE_TIMEOUT}s")
        try:
            proc.kill()
        except:
            pass
        return False, "Timeout"

    except Exception as e:
        log.exception(f"Error invoking Claude: {e}")
        return False, str(e)


async def daemon_loop():
    """Main daemon loop."""
    log.info("=" * 60)
    log.info("Hyperion Daemon starting...")
    log.info(f"Workspace: {WORKSPACE}")
    log.info(f"Inbox: {INBOX_DIR}")
    log.info("=" * 60)

    # Ensure directories exist
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    INBOX_DIR.mkdir(parents=True, exist_ok=True)

    consecutive_errors = 0
    max_errors = 5

    while True:
        loop_start = time.time()

        try:
            msg_count = count_inbox_messages()

            if msg_count > 0:
                log.info(f"📬 {msg_count} message(s) in inbox")

                success, output = await process_messages()

                if success:
                    consecutive_errors = 0
                    remaining = count_inbox_messages()
                    processed = msg_count - remaining
                    log.info(f"✅ Processed {processed}, {remaining} remaining")
                else:
                    consecutive_errors += 1
                    log.warning(f"⚠️ Failed ({consecutive_errors}/{max_errors})")

                    if consecutive_errors >= max_errors:
                        log.error("Too many errors. Sleeping 60s...")
                        await asyncio.sleep(60)
                        consecutive_errors = 0

                poll = POLL_INTERVAL
            else:
                poll = IDLE_POLL_INTERVAL

        except Exception as e:
            log.exception(f"Loop error: {e}")
            consecutive_errors += 1
            poll = POLL_INTERVAL

        elapsed = time.time() - loop_start
        sleep_time = max(poll - elapsed, 1)
        await asyncio.sleep(sleep_time)


def main():
    """Entry point."""
    try:
        asyncio.run(daemon_loop())
    except KeyboardInterrupt:
        log.info("Daemon stopped by user")
    except Exception as e:
        log.exception(f"Daemon crashed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
