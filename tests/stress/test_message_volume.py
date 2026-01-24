"""
Tests for High Message Volume

Tests system behavior with 1000+ messages using static fixtures.
"""

import asyncio
import json
import pytest
import time
from pathlib import Path
from unittest.mock import patch


@pytest.mark.stress
@pytest.mark.slow
class TestMessageVolume:
    """Tests for high message volume handling."""

    @pytest.fixture
    def inbox_dir(self, temp_messages_dir: Path) -> Path:
        """Get inbox directory."""
        return temp_messages_dir / "inbox"

    @pytest.fixture
    def stress_messages(self, fixture_loader) -> list[dict]:
        """Load pre-generated stress messages from static fixture."""
        return fixture_loader.load_stress_messages()

    def test_create_1000_messages(self, inbox_dir: Path, stress_messages: list[dict]):
        """Test creating 1000 message files from static fixtures."""
        start_time = time.time()

        for msg in stress_messages:
            msg_file = inbox_dir / f"{msg['id']}.json"
            msg_file.write_text(json.dumps(msg))

        elapsed = time.time() - start_time

        # Should complete reasonably quickly (< 30 seconds)
        assert elapsed < 30, f"Creating 1000 messages took {elapsed:.2f}s"

        # Verify all files exist
        files = list(inbox_dir.glob("*.json"))
        assert len(files) == len(stress_messages)

    def test_read_1000_messages(self, inbox_dir: Path, stress_messages: list[dict]):
        """Test reading 1000 message files."""
        # Create messages first from static fixtures
        for msg in stress_messages:
            (inbox_dir / f"{msg['id']}.json").write_text(json.dumps(msg))

        start_time = time.time()

        messages = []
        for f in inbox_dir.glob("*.json"):
            messages.append(json.loads(f.read_text()))

        elapsed = time.time() - start_time

        assert len(messages) == len(stress_messages)
        assert elapsed < 30, f"Reading 1000 messages took {elapsed:.2f}s"

    @pytest.mark.asyncio
    async def test_check_inbox_with_1000_messages(
        self, inbox_dir: Path, stress_messages: list[dict]
    ):
        """Test check_inbox tool with 1000 messages."""
        # Create messages from static fixtures
        for msg in stress_messages:
            (inbox_dir / f"{msg['id']}.json").write_text(json.dumps(msg))

        with patch("src.mcp.inbox_server.INBOX_DIR", inbox_dir):
            from src.mcp.inbox_server import handle_check_inbox

            start_time = time.time()

            # Default limit is 10
            result = await handle_check_inbox({"limit": 10})

            elapsed = time.time() - start_time

            # Should return quickly despite 1000 files
            assert elapsed < 5, f"check_inbox took {elapsed:.2f}s"
            assert "10 new message" in result[0].text

    @pytest.mark.asyncio
    async def test_check_inbox_high_limit(
        self, inbox_dir: Path, stress_messages: list[dict]
    ):
        """Test check_inbox with high limit."""
        # Use first 100 messages from static fixtures
        for msg in stress_messages[:100]:
            (inbox_dir / f"{msg['id']}.json").write_text(json.dumps(msg))

        with patch("src.mcp.inbox_server.INBOX_DIR", inbox_dir):
            from src.mcp.inbox_server import handle_check_inbox

            start_time = time.time()

            result = await handle_check_inbox({"limit": 100})

            elapsed = time.time() - start_time

            assert elapsed < 10, f"check_inbox with limit=100 took {elapsed:.2f}s"
            assert "100 new message" in result[0].text


@pytest.mark.stress
@pytest.mark.slow
class TestMessageThroughput:
    """Tests for message throughput."""

    @pytest.fixture
    def message_system(self, temp_messages_dir: Path):
        """Set up message system directories."""
        (temp_messages_dir / "tasks.json").write_text(
            json.dumps({"tasks": [], "next_id": 1})
        )
        return {
            "inbox": temp_messages_dir / "inbox",
            "outbox": temp_messages_dir / "outbox",
            "processed": temp_messages_dir / "processed",
        }

    @pytest.fixture
    def text_messages(self, fixture_loader) -> list[dict]:
        """Load pre-generated text messages from static fixture."""
        return fixture_loader.load_text_messages()

    @pytest.mark.asyncio
    async def test_process_messages_sequentially(
        self, message_system, text_messages: list[dict]
    ):
        """Test processing messages sequentially using static fixtures."""
        inbox = message_system["inbox"]
        outbox = message_system["outbox"]
        processed = message_system["processed"]

        # Create messages from static fixtures (use all available)
        for msg in text_messages:
            (inbox / f"{msg['id']}.json").write_text(json.dumps(msg))

        message_count = len(text_messages)

        with patch.multiple(
            "src.mcp.inbox_server",
            INBOX_DIR=inbox,
            OUTBOX_DIR=outbox,
            PROCESSED_DIR=processed,
        ):
            from src.mcp.inbox_server import (
                handle_check_inbox,
                handle_send_reply,
                handle_mark_processed,
            )

            start_time = time.time()
            processed_count = 0

            # Process each message
            while True:
                result = await handle_check_inbox({"limit": 1})
                if "No new messages" in result[0].text:
                    break

                # Extract chat_id from result (simplified)
                chat_id = 123456  # In real scenario, parse from result

                await handle_send_reply({
                    "chat_id": chat_id,
                    "text": "Processed!",
                })

                # Mark first message as processed
                inbox_files = list(inbox.glob("*.json"))
                if inbox_files:
                    msg_data = json.loads(inbox_files[0].read_text())
                    await handle_mark_processed({"message_id": msg_data["id"]})
                    processed_count += 1

            elapsed = time.time() - start_time

            assert processed_count == message_count
            # Should process at reasonable rate (> 2 msg/sec for smaller batches)
            rate = processed_count / elapsed if elapsed > 0 else float('inf')
            assert rate > 2, f"Processing rate {rate:.1f} msg/s is too slow"


@pytest.mark.stress
@pytest.mark.slow
class TestStatsWithHighVolume:
    """Tests for stats tool with high message volume."""

    @pytest.fixture
    def populated_system(self, temp_messages_dir: Path, fixture_loader):
        """Create system with many messages using static fixtures."""
        inbox = temp_messages_dir / "inbox"
        outbox = temp_messages_dir / "outbox"
        processed = temp_messages_dir / "processed"

        # Load static fixtures
        stress_messages = fixture_loader.load_stress_messages()
        text_messages = fixture_loader.load_text_messages()

        # Create messages in each directory from static data
        for i, msg in enumerate(text_messages[:10]):
            (inbox / f"inbox_{i}.json").write_text(json.dumps(msg))

        for i in range(50):
            (outbox / f"outbox_{i}.json").write_text(
                json.dumps({"chat_id": i, "text": "reply"})
            )

        for i, msg in enumerate(stress_messages[:500]):
            (processed / f"processed_{i}.json").write_text(json.dumps(msg))

        return inbox, outbox, processed

    @pytest.mark.asyncio
    async def test_get_stats_performance(self, populated_system):
        """Test get_stats performance with many files."""
        inbox, outbox, processed = populated_system

        with patch.multiple(
            "src.mcp.inbox_server",
            INBOX_DIR=inbox,
            OUTBOX_DIR=outbox,
            PROCESSED_DIR=processed,
        ):
            from src.mcp.inbox_server import handle_get_stats

            start_time = time.time()

            result = await handle_get_stats({})

            elapsed = time.time() - start_time

            # Should complete quickly
            assert elapsed < 5, f"get_stats took {elapsed:.2f}s"

            # Verify counts are in output
            assert "10" in result[0].text  # inbox
            assert "50" in result[0].text  # outbox
            assert "500" in result[0].text  # processed
