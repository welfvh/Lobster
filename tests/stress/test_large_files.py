"""
Tests for Large File Handling

Tests handling of large message payloads and files using static fixtures.
"""

import asyncio
import json
import pytest
import time
from pathlib import Path
from unittest.mock import patch


@pytest.mark.stress
@pytest.mark.slow
class TestLargeMessages:
    """Tests for large message handling."""

    @pytest.fixture
    def inbox_dir(self, temp_messages_dir: Path) -> Path:
        """Get inbox directory."""
        return temp_messages_dir / "inbox"

    @pytest.fixture
    def edge_cases(self, fixture_loader) -> list[dict]:
        """Load pre-generated edge case messages from static fixture."""
        return fixture_loader.load_edge_case_messages()

    @pytest.fixture
    def text_messages(self, fixture_loader) -> list[dict]:
        """Load pre-generated text messages from static fixture."""
        return fixture_loader.load_text_messages()

    def test_large_text_message_10kb(self, inbox_dir: Path, text_messages: list[dict]):
        """Test handling 10KB text message."""
        # Create large text using pattern from static fixture
        base_text = text_messages[0]["text"] if text_messages else "test"
        large_text = (base_text + " ") * (10240 // (len(base_text) + 1) + 1)
        large_text = large_text[:10240]

        msg = text_messages[0].copy()
        msg["id"] = "large_10kb_test"
        msg["text"] = large_text

        msg_file = inbox_dir / f"{msg['id']}.json"
        msg_file.write_text(json.dumps(msg))

        # Read back and verify
        content = json.loads(msg_file.read_text())
        assert len(content["text"]) == 10240

    def test_large_text_message_100kb(self, inbox_dir: Path, text_messages: list[dict]):
        """Test handling 100KB text message."""
        base_text = text_messages[0]["text"] if text_messages else "test"
        large_text = (base_text + " ") * (102400 // (len(base_text) + 1) + 1)
        large_text = large_text[:102400]

        msg = text_messages[0].copy()
        msg["id"] = "large_100kb_test"
        msg["text"] = large_text

        msg_file = inbox_dir / f"{msg['id']}.json"
        msg_file.write_text(json.dumps(msg))

        content = json.loads(msg_file.read_text())
        assert len(content["text"]) == 102400

    def test_large_text_message_1mb(self, inbox_dir: Path, text_messages: list[dict]):
        """Test handling 1MB text message."""
        base_text = text_messages[0]["text"] if text_messages else "test"
        large_text = (base_text + " ") * (1048576 // (len(base_text) + 1) + 1)
        large_text = large_text[:1048576]

        msg = text_messages[0].copy()
        msg["id"] = "large_1mb_test"
        msg["text"] = large_text

        msg_file = inbox_dir / f"{msg['id']}.json"

        start_time = time.time()
        msg_file.write_text(json.dumps(msg))
        write_time = time.time() - start_time

        start_time = time.time()
        content = json.loads(msg_file.read_text())
        read_time = time.time() - start_time

        assert len(content["text"]) == 1048576
        # Should complete in reasonable time
        assert write_time < 5, f"Write took {write_time:.2f}s"
        assert read_time < 5, f"Read took {read_time:.2f}s"

    @pytest.mark.asyncio
    async def test_check_inbox_with_large_messages(
        self, inbox_dir: Path, text_messages: list[dict], edge_cases: list[dict]
    ):
        """Test check_inbox with large messages using static fixtures."""
        # Create normal messages from static fixtures
        for i, msg in enumerate(text_messages[:5]):
            modified_msg = msg.copy()
            modified_msg["id"] = f"normal_{i}_{msg['id']}"
            (inbox_dir / f"normal_{i}.json").write_text(json.dumps(modified_msg))

        # Create large messages based on edge cases
        for i in range(3):
            base_msg = edge_cases[i % len(edge_cases)].copy()
            # Make it large by repeating the text
            base_msg["id"] = f"large_{i}"
            base_msg["text"] = (base_msg["text"] + " ") * 1000  # ~100KB each
            (inbox_dir / f"large_{i}.json").write_text(json.dumps(base_msg))

        with patch("src.mcp.inbox_server.INBOX_DIR", inbox_dir):
            from src.mcp.inbox_server import handle_check_inbox

            start_time = time.time()
            result = await handle_check_inbox({"limit": 10})
            elapsed = time.time() - start_time

            assert "8 new message" in result[0].text
            assert elapsed < 5, f"check_inbox took {elapsed:.2f}s"


@pytest.mark.stress
@pytest.mark.slow
class TestLargeTaskFiles:
    """Tests for large task file handling."""

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
    async def test_task_with_large_description(self, tasks_file: Path, sample_tasks: dict):
        """Test task with large description using static fixture as base."""
        # Use description from static fixture and expand it
        base_desc = sample_tasks["tasks"][0]["description"] if sample_tasks["tasks"] else "Task details"
        large_description = (base_desc + " ") * 5000  # ~50KB

        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import (
                handle_create_task,
                handle_get_task,
            )

            await handle_create_task({
                "subject": "Task with large description",
                "description": large_description,
            })

            result = await handle_get_task({"task_id": 1})

            # Description should be preserved (at least partially shown)
            assert "Task" in result[0].text or "description" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_many_tasks(self, tasks_file: Path, sample_tasks: dict):
        """Test handling many tasks using static fixture templates."""
        # Get subjects from static fixture to use as templates
        template_subjects = [t["subject"] for t in sample_tasks["tasks"]]

        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import (
                handle_create_task,
                handle_list_tasks,
            )

            # Create 500 tasks
            start_time = time.time()
            for i in range(500):
                subject_template = template_subjects[i % len(template_subjects)]
                await handle_create_task({
                    "subject": f"{subject_template} #{i}",
                    "description": f"Description for task {i}",
                })
            create_time = time.time() - start_time

            # List all tasks
            start_time = time.time()
            result = await handle_list_tasks({})
            list_time = time.time() - start_time

            assert "500" in result[0].text
            assert create_time < 30, f"Creating 500 tasks took {create_time:.2f}s"
            assert list_time < 5, f"Listing 500 tasks took {list_time:.2f}s"


@pytest.mark.stress
@pytest.mark.slow
class TestLargeJobOutputs:
    """Tests for large job output handling."""

    @pytest.fixture
    def outputs_dir(self, temp_messages_dir: Path) -> Path:
        """Get outputs directory."""
        return temp_messages_dir / "task-outputs"

    @pytest.fixture
    def scheduled_jobs(self, fixture_loader) -> dict:
        """Load pre-generated scheduled jobs from static fixture."""
        return fixture_loader.load_scheduled_jobs()

    @pytest.mark.asyncio
    async def test_large_job_output(self, outputs_dir: Path, scheduled_jobs: dict):
        """Test writing large job output using static fixture job names."""
        job_names = list(scheduled_jobs.get("jobs", {}).keys())
        job_name = job_names[0] if job_names else "test-job"

        large_output = "=" * 50 + "\n"
        large_output += ("Result line: processing data batch\n") * 100
        large_output += "=" * 50

        with patch("src.mcp.inbox_server.TASK_OUTPUTS_DIR", outputs_dir):
            from src.mcp.inbox_server import (
                handle_write_task_output,
                handle_check_task_outputs,
            )

            await handle_write_task_output({
                "job_name": job_name,
                "output": large_output,
                "status": "success",
            })

            result = await handle_check_task_outputs({})

            # Should handle large output
            assert job_name in result[0].text

    @pytest.mark.asyncio
    async def test_many_job_outputs(self, outputs_dir: Path, scheduled_jobs: dict):
        """Test handling many job outputs using static fixture job names."""
        job_names = list(scheduled_jobs.get("jobs", {}).keys())
        if not job_names:
            job_names = ["job-0", "job-1", "job-2"]

        with patch("src.mcp.inbox_server.TASK_OUTPUTS_DIR", outputs_dir):
            from src.mcp.inbox_server import (
                handle_write_task_output,
                handle_check_task_outputs,
            )

            # Create 200 outputs using job names from static fixture
            for i in range(200):
                job_name = job_names[i % len(job_names)]
                await handle_write_task_output({
                    "job_name": job_name,
                    "output": f"Output number {i}",
                    "status": "success" if i % 5 != 0 else "failed",
                })

            # Check outputs
            start_time = time.time()
            result = await handle_check_task_outputs({"limit": 50})
            elapsed = time.time() - start_time

            assert elapsed < 5, f"Checking outputs took {elapsed:.2f}s"


@pytest.mark.stress
@pytest.mark.slow
class TestEdgeCasePayloads:
    """Tests for edge case payloads using static fixtures."""

    @pytest.fixture
    def inbox_dir(self, temp_messages_dir: Path) -> Path:
        """Get inbox directory."""
        return temp_messages_dir / "inbox"

    @pytest.fixture
    def edge_cases(self, fixture_loader) -> list[dict]:
        """Load pre-generated edge case messages from static fixture."""
        return fixture_loader.load_edge_case_messages()

    def test_unicode_heavy_message(self, inbox_dir: Path, edge_cases: list[dict]):
        """Test message with heavy Unicode content from static fixture."""
        # Find Unicode-heavy message from edge cases
        unicode_msg = None
        for msg in edge_cases:
            if any(ord(c) > 127 for c in msg.get("text", "")):
                unicode_msg = msg
                break

        if unicode_msg is None:
            # Create one if not in fixtures
            unicode_msg = edge_cases[0].copy() if edge_cases else {"id": "unicode_test"}
            unicode_msg["text"] = "\U0001f600\U0001f389\U0001f680 \u4e2d\u6587 \u05e2\u05d1\u05e8\u05d9\u05ea" * 100
            unicode_msg["id"] = "unicode_test"

        msg_file = inbox_dir / f"{unicode_msg['id']}.json"
        msg_file.write_text(json.dumps(unicode_msg, ensure_ascii=False))

        content = json.loads(msg_file.read_text())
        assert content["text"] == unicode_msg["text"]

    def test_special_characters_in_message(self, inbox_dir: Path, edge_cases: list[dict]):
        """Test message with special JSON characters from static fixture."""
        # Find message with special characters from edge cases
        special_msg = None
        for msg in edge_cases:
            text = msg.get("text", "")
            if any(c in text for c in ['{', '}', '"', '\\', '\n', '\t']):
                special_msg = msg
                break

        if special_msg is None:
            special_msg = edge_cases[0].copy() if edge_cases else {"id": "special_test"}
            special_msg["text"] = r'{"key": "value", "nested": {"array": [1, 2, 3]}}' + '\n\t\r"quotes"'
            special_msg["id"] = "special_test"

        msg_file = inbox_dir / f"{special_msg['id']}.json"
        msg_file.write_text(json.dumps(special_msg))

        content = json.loads(msg_file.read_text())
        assert content["text"] == special_msg["text"]

    def test_all_edge_cases_from_fixture(self, inbox_dir: Path, edge_cases: list[dict]):
        """Test all edge cases from the static fixture."""
        for i, msg in enumerate(edge_cases):
            modified_msg = msg.copy()
            modified_msg["id"] = f"edge_{i}_{msg.get('id', 'test')}"

            msg_file = inbox_dir / f"edge_{i}.json"
            msg_file.write_text(json.dumps(modified_msg, ensure_ascii=False))

            # Verify round-trip
            content = json.loads(msg_file.read_text())
            assert content["text"] == modified_msg["text"]

        # All edge cases should be written successfully
        files = list(inbox_dir.glob("edge_*.json"))
        assert len(files) == len(edge_cases)
