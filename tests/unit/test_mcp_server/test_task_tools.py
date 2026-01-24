"""
Tests for MCP Server Task Management Tools

Tests list_tasks, create_task, update_task, get_task, delete_task
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch
import asyncio


class TestListTasks:
    """Tests for list_tasks tool."""

    @pytest.fixture
    def tasks_file(self, temp_messages_dir: Path, task_generator) -> Path:
        """Create a tasks file with sample tasks."""
        tasks = [
            task_generator.generate_task(status="pending"),
            task_generator.generate_task(status="in_progress"),
            task_generator.generate_task(status="completed"),
            task_generator.generate_task(status="pending"),
        ]
        data = {"tasks": tasks, "next_id": 5}
        tasks_path = temp_messages_dir / "tasks.json"
        tasks_path.write_text(json.dumps(data))
        return tasks_path

    def test_returns_all_tasks(self, tasks_file: Path):
        """Test that all tasks are returned by default."""
        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_list_tasks

            result = asyncio.run(handle_list_tasks({}))

            assert "Tasks" in result[0].text
            assert "4" in result[0].text  # Total count

    def test_filters_by_status(self, tasks_file: Path):
        """Test status filter works correctly."""
        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_list_tasks

            result = asyncio.run(handle_list_tasks({"status": "pending"}))

            # Should only show pending tasks
            assert "Pending" in result[0].text

    def test_groups_tasks_by_status(self, tasks_file: Path):
        """Test that tasks are grouped by status."""
        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_list_tasks

            result = asyncio.run(handle_list_tasks({"status": "all"}))

            # Check for status headers
            text = result[0].text
            assert "In Progress" in text or "in_progress" in text.lower()

    def test_empty_tasks_returns_no_tasks(self, temp_messages_dir: Path):
        """Test that empty task list returns appropriate message."""
        empty_tasks = temp_messages_dir / "tasks.json"
        empty_tasks.write_text(json.dumps({"tasks": [], "next_id": 1}))

        with patch("src.mcp.inbox_server.TASKS_FILE", empty_tasks):
            from src.mcp.inbox_server import handle_list_tasks

            result = asyncio.run(handle_list_tasks({}))

            assert "No tasks" in result[0].text


class TestCreateTask:
    """Tests for create_task tool."""

    @pytest.fixture
    def tasks_file(self, temp_messages_dir: Path) -> Path:
        """Create an empty tasks file."""
        tasks_path = temp_messages_dir / "tasks.json"
        tasks_path.write_text(json.dumps({"tasks": [], "next_id": 1}))
        return tasks_path

    def test_creates_task(self, tasks_file: Path):
        """Test that task is created successfully."""
        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_create_task

            result = asyncio.run(
                handle_create_task({
                    "subject": "Test Task",
                    "description": "Test description",
                })
            )

            assert "created" in result[0].text.lower()
            assert "#1" in result[0].text

            # Verify task was saved
            data = json.loads(tasks_file.read_text())
            assert len(data["tasks"]) == 1
            assert data["tasks"][0]["subject"] == "Test Task"
            assert data["next_id"] == 2

    def test_requires_subject(self, tasks_file: Path):
        """Test that subject is required."""
        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_create_task

            result = asyncio.run(handle_create_task({"description": "No subject"}))

            assert "Error" in result[0].text
            assert "subject" in result[0].text.lower()

    def test_description_is_optional(self, tasks_file: Path):
        """Test that description is optional."""
        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_create_task

            result = asyncio.run(handle_create_task({"subject": "No description"}))

            assert "created" in result[0].text.lower()

    def test_increments_next_id(self, tasks_file: Path):
        """Test that next_id is incremented."""
        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_create_task

            asyncio.run(handle_create_task({"subject": "Task 1"}))
            asyncio.run(handle_create_task({"subject": "Task 2"}))
            asyncio.run(handle_create_task({"subject": "Task 3"}))

            data = json.loads(tasks_file.read_text())
            assert data["next_id"] == 4
            assert len(data["tasks"]) == 3

    def test_sets_default_status_pending(self, tasks_file: Path):
        """Test that new tasks have pending status."""
        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_create_task

            asyncio.run(handle_create_task({"subject": "New Task"}))

            data = json.loads(tasks_file.read_text())
            assert data["tasks"][0]["status"] == "pending"


class TestUpdateTask:
    """Tests for update_task tool."""

    @pytest.fixture
    def tasks_file(self, temp_messages_dir: Path, task_generator) -> Path:
        """Create tasks file with sample task."""
        task = task_generator.generate_task(task_id=1, status="pending")
        data = {"tasks": [task], "next_id": 2}
        tasks_path = temp_messages_dir / "tasks.json"
        tasks_path.write_text(json.dumps(data))
        return tasks_path

    def test_updates_status(self, tasks_file: Path):
        """Test that task status can be updated."""
        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_update_task

            result = asyncio.run(
                handle_update_task({"task_id": 1, "status": "in_progress"})
            )

            assert "updated" in result[0].text.lower()

            data = json.loads(tasks_file.read_text())
            assert data["tasks"][0]["status"] == "in_progress"

    def test_updates_subject(self, tasks_file: Path):
        """Test that task subject can be updated."""
        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_update_task

            asyncio.run(
                handle_update_task({"task_id": 1, "subject": "Updated Subject"})
            )

            data = json.loads(tasks_file.read_text())
            assert data["tasks"][0]["subject"] == "Updated Subject"

    def test_updates_description(self, tasks_file: Path):
        """Test that task description can be updated."""
        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_update_task

            asyncio.run(
                handle_update_task({"task_id": 1, "description": "New description"})
            )

            data = json.loads(tasks_file.read_text())
            assert data["tasks"][0]["description"] == "New description"

    def test_invalid_status_returns_error(self, tasks_file: Path):
        """Test that invalid status returns error."""
        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_update_task

            result = asyncio.run(
                handle_update_task({"task_id": 1, "status": "invalid_status"})
            )

            assert "Error" in result[0].text
            assert "Invalid status" in result[0].text

    def test_nonexistent_task_returns_error(self, tasks_file: Path):
        """Test that updating nonexistent task returns error."""
        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_update_task

            result = asyncio.run(
                handle_update_task({"task_id": 999, "status": "completed"})
            )

            assert "Error" in result[0].text
            assert "not found" in result[0].text.lower()

    def test_requires_task_id(self, tasks_file: Path):
        """Test that task_id is required."""
        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_update_task

            result = asyncio.run(handle_update_task({"status": "completed"}))

            assert "Error" in result[0].text

    def test_updates_updated_at_timestamp(self, tasks_file: Path):
        """Test that updated_at is set on update."""
        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_update_task

            old_data = json.loads(tasks_file.read_text())
            old_updated = old_data["tasks"][0]["updated_at"]

            import time
            time.sleep(0.1)

            asyncio.run(handle_update_task({"task_id": 1, "status": "completed"}))

            new_data = json.loads(tasks_file.read_text())
            new_updated = new_data["tasks"][0]["updated_at"]

            assert new_updated != old_updated


class TestGetTask:
    """Tests for get_task tool."""

    @pytest.fixture
    def tasks_file(self, temp_messages_dir: Path, task_generator) -> Path:
        """Create tasks file with sample task."""
        task = task_generator.generate_task(
            task_id=1,
            subject="Test Subject",
            description="Test description",
            status="pending",
        )
        data = {"tasks": [task], "next_id": 2}
        tasks_path = temp_messages_dir / "tasks.json"
        tasks_path.write_text(json.dumps(data))
        return tasks_path

    def test_returns_task_details(self, tasks_file: Path):
        """Test that task details are returned."""
        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_get_task

            result = asyncio.run(handle_get_task({"task_id": 1}))

            text = result[0].text
            assert "Test Subject" in text
            assert "Test description" in text
            assert "pending" in text.lower()

    def test_nonexistent_task_returns_error(self, tasks_file: Path):
        """Test that nonexistent task returns error."""
        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_get_task

            result = asyncio.run(handle_get_task({"task_id": 999}))

            assert "Error" in result[0].text
            assert "not found" in result[0].text.lower()

    def test_requires_task_id(self, tasks_file: Path):
        """Test that task_id is required."""
        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_get_task

            result = asyncio.run(handle_get_task({}))

            assert "Error" in result[0].text


class TestDeleteTask:
    """Tests for delete_task tool."""

    @pytest.fixture
    def tasks_file(self, temp_messages_dir: Path, task_generator) -> Path:
        """Create tasks file with sample tasks."""
        tasks = [
            task_generator.generate_task(task_id=1),
            task_generator.generate_task(task_id=2),
        ]
        data = {"tasks": tasks, "next_id": 3}
        tasks_path = temp_messages_dir / "tasks.json"
        tasks_path.write_text(json.dumps(data))
        return tasks_path

    def test_deletes_task(self, tasks_file: Path):
        """Test that task is deleted."""
        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_delete_task

            result = asyncio.run(handle_delete_task({"task_id": 1}))

            assert "deleted" in result[0].text.lower()

            data = json.loads(tasks_file.read_text())
            assert len(data["tasks"]) == 1
            assert data["tasks"][0]["id"] == 2

    def test_nonexistent_task_returns_error(self, tasks_file: Path):
        """Test that deleting nonexistent task returns error."""
        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_delete_task

            result = asyncio.run(handle_delete_task({"task_id": 999}))

            assert "Error" in result[0].text
            assert "not found" in result[0].text.lower()

    def test_requires_task_id(self, tasks_file: Path):
        """Test that task_id is required."""
        with patch("src.mcp.inbox_server.TASKS_FILE", tasks_file):
            from src.mcp.inbox_server import handle_delete_task

            result = asyncio.run(handle_delete_task({}))

            assert "Error" in result[0].text
