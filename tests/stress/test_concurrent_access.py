"""
Tests for Concurrent File Access

Tests multi-threaded file access and race conditions using static fixtures.
"""

import asyncio
import json
import pytest
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch


@pytest.mark.stress
@pytest.mark.slow
class TestConcurrentFileWrites:
    """Tests for concurrent file writing."""

    @pytest.fixture
    def inbox_dir(self, temp_messages_dir: Path) -> Path:
        """Get inbox directory."""
        return temp_messages_dir / "inbox"

    @pytest.fixture
    def stress_messages(self, fixture_loader) -> list[dict]:
        """Load pre-generated stress messages from static fixture."""
        return fixture_loader.load_stress_messages()

    def test_concurrent_message_creation(
        self, inbox_dir: Path, stress_messages: list[dict]
    ):
        """Test creating messages concurrently from multiple threads using static fixtures."""
        num_threads = 10
        messages_per_thread = 50
        errors = []

        # Partition static messages across threads
        def create_messages(thread_id):
            try:
                start_idx = thread_id * messages_per_thread
                end_idx = start_idx + messages_per_thread
                thread_messages = stress_messages[start_idx:end_idx]

                for i, msg in enumerate(thread_messages):
                    msg_file = inbox_dir / f"t{thread_id}_{i}_{msg['id']}.json"
                    msg_file.write_text(json.dumps(msg))
            except Exception as e:
                errors.append((thread_id, e))

        start_time = time.time()

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [
                executor.submit(create_messages, i)
                for i in range(num_threads)
            ]
            for future in as_completed(futures):
                future.result()

        elapsed = time.time() - start_time

        # Check for errors
        assert len(errors) == 0, f"Errors occurred: {errors}"

        # Verify all files were created
        files = list(inbox_dir.glob("*.json"))
        expected = num_threads * messages_per_thread
        assert len(files) == expected, f"Expected {expected}, got {len(files)}"

        # Should complete reasonably
        assert elapsed < 30, f"Concurrent creation took {elapsed:.2f}s"

    def test_concurrent_read_write(
        self, inbox_dir: Path, stress_messages: list[dict]
    ):
        """Test concurrent reading and writing using static fixtures."""
        # Pre-populate with some messages from static fixtures
        for i, msg in enumerate(stress_messages[:50]):
            (inbox_dir / f"initial_{i}.json").write_text(json.dumps(msg))

        read_results = []
        write_errors = []
        read_errors = []

        # Use next batch of static messages for writers
        writer_messages = stress_messages[50:110]  # 60 messages for 3 writers

        def writer(thread_id):
            try:
                start_idx = thread_id * 20
                for i in range(20):
                    msg = writer_messages[start_idx + i]
                    (inbox_dir / f"writer{thread_id}_{i}.json").write_text(
                        json.dumps(msg)
                    )
                    time.sleep(0.01)  # Small delay
            except Exception as e:
                write_errors.append((thread_id, e))

        def reader(thread_id):
            try:
                for _ in range(20):
                    files = list(inbox_dir.glob("*.json"))
                    for f in files[:5]:  # Read first 5
                        try:
                            content = json.loads(f.read_text())
                            read_results.append(content.get("id"))
                        except (json.JSONDecodeError, FileNotFoundError):
                            # File might be deleted/modified
                            pass
                    time.sleep(0.01)
            except Exception as e:
                read_errors.append((thread_id, e))

        with ThreadPoolExecutor(max_workers=6) as executor:
            # 3 writers, 3 readers
            futures = []
            for i in range(3):
                futures.append(executor.submit(writer, i))
                futures.append(executor.submit(reader, i))

            for future in as_completed(futures):
                future.result()

        # Should complete without critical errors
        assert len(write_errors) == 0, f"Write errors: {write_errors}"
        assert len(read_errors) == 0, f"Read errors: {read_errors}"
        assert len(read_results) > 0, "Should have read some messages"


@pytest.mark.stress
@pytest.mark.slow
class TestConcurrentTaskAccess:
    """Tests for concurrent task file access."""

    @pytest.fixture
    def tasks_file(self, temp_messages_dir: Path) -> Path:
        """Create tasks file."""
        tasks_path = temp_messages_dir / "tasks.json"
        tasks_path.write_text(json.dumps({"tasks": [], "next_id": 1}))
        return tasks_path

    @pytest.fixture
    def sample_tasks(self, fixture_loader) -> dict:
        """Load pre-generated tasks from static fixture."""
        return fixture_loader.load_sample_tasks()

    @pytest.mark.asyncio
    async def test_concurrent_task_creation(self, tasks_file: Path, sample_tasks: dict):
        """Test creating tasks concurrently using static task subjects."""
        # Use subjects from static fixture as templates
        task_subjects = [t["subject"] for t in sample_tasks["tasks"]]

        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_create_task

            async def create_task(i):
                subject = f"{task_subjects[i % len(task_subjects)]} #{i}"
                await handle_create_task({
                    "subject": subject,
                    "description": f"Description for task {i}",
                })

            # Create 50 tasks concurrently
            tasks = [create_task(i) for i in range(50)]
            await asyncio.gather(*tasks)

            # Verify tasks were created
            data = json.loads(tasks_file.read_text())

            # Due to race conditions, we might not get exactly 50
            # but should have a significant number
            assert len(data["tasks"]) >= 40, f"Only {len(data['tasks'])} tasks created"

    @pytest.mark.asyncio
    async def test_concurrent_task_updates(self, tasks_file: Path, sample_tasks: dict):
        """Test updating tasks concurrently."""
        # Pre-create tasks using static fixture structure
        tasks_data = {
            "tasks": [
                {"id": i, "subject": f"Task {i}", "description": "", "status": "pending"}
                for i in range(1, 21)
            ],
            "next_id": 21,
        }
        tasks_file.write_text(json.dumps(tasks_data))

        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_update_task

            async def update_task(task_id):
                await handle_update_task({
                    "task_id": task_id,
                    "status": "completed",
                })

            # Update all tasks concurrently
            updates = [update_task(i) for i in range(1, 21)]
            await asyncio.gather(*updates)

            # Verify updates
            data = json.loads(tasks_file.read_text())
            completed = [t for t in data["tasks"] if t.get("status") == "completed"]

            # Should have updated most tasks
            assert len(completed) >= 15


@pytest.mark.stress
@pytest.mark.slow
class TestConcurrentOutbox:
    """Tests for concurrent outbox operations."""

    @pytest.fixture
    def outbox_dir(self, temp_messages_dir: Path) -> Path:
        """Get outbox directory."""
        return temp_messages_dir / "outbox"

    @pytest.fixture
    def text_messages(self, fixture_loader) -> list[dict]:
        """Load pre-generated text messages for reply content."""
        return fixture_loader.load_text_messages()

    def test_concurrent_reply_creation(self, outbox_dir: Path, text_messages: list[dict]):
        """Test creating reply files concurrently using static fixtures."""
        num_threads = 5
        replies_per_thread = 20

        def create_replies(thread_id):
            for i in range(replies_per_thread):
                # Use text from static fixtures
                source_msg = text_messages[i % len(text_messages)]
                reply = {
                    "id": f"reply_t{thread_id}_{i}",
                    "chat_id": thread_id * 1000 + i,
                    "text": f"Reply to: {source_msg['text'][:50]}",
                }
                reply_file = outbox_dir / f"t{thread_id}_{i}.json"
                reply_file.write_text(json.dumps(reply))

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [
                executor.submit(create_replies, i)
                for i in range(num_threads)
            ]
            for future in as_completed(futures):
                future.result()

        # Verify all replies created
        files = list(outbox_dir.glob("*.json"))
        expected = num_threads * replies_per_thread
        assert len(files) == expected

    def test_concurrent_reply_processing(self, outbox_dir: Path, text_messages: list[dict]):
        """Test processing (reading and deleting) reply files concurrently."""
        # Pre-create reply files using static fixture content
        for i in range(100):
            source_msg = text_messages[i % len(text_messages)]
            reply = {
                "id": f"reply_{i}",
                "chat_id": i,
                "text": f"Reply {i}: {source_msg['text'][:30]}",
            }
            (outbox_dir / f"reply_{i}.json").write_text(json.dumps(reply))

        processed = []
        errors = []
        lock = threading.Lock()

        def process_reply(file_path):
            try:
                # Read
                content = json.loads(Path(file_path).read_text())
                with lock:
                    processed.append(content["id"])
                # Delete
                Path(file_path).unlink()
            except FileNotFoundError:
                # Already processed by another thread
                pass
            except Exception as e:
                with lock:
                    errors.append(e)

        files = list(outbox_dir.glob("*.json"))

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(process_reply, str(f)) for f in files]
            for future in as_completed(futures):
                future.result()

        # All files should be processed
        remaining = list(outbox_dir.glob("*.json"))
        assert len(remaining) == 0
        assert len(errors) == 0
        assert len(processed) == 100
