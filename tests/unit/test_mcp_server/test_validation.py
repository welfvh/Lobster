"""
Tests for MCP Server Validation Functions

Tests cron validation, job name validation, and other validators.
"""

import pytest


class TestValidateCronSchedule:
    """Tests for cron schedule validation."""

    def test_valid_simple_schedule(self):
        """Test valid simple cron schedules."""
        from src.mcp.inbox_server import validate_cron_schedule

        valid_schedules = [
            "* * * * *",
            "0 0 * * *",
            "30 8 * * *",
            "0 9 * * 1",
            "*/5 * * * *",
            "0 */2 * * *",
            "0 0 1 * *",
            "0 0 * * 0",
        ]

        for schedule in valid_schedules:
            valid, error = validate_cron_schedule(schedule)
            assert valid, f"Schedule '{schedule}' should be valid: {error}"

    def test_invalid_part_count(self):
        """Test that wrong number of parts is rejected."""
        from src.mcp.inbox_server import validate_cron_schedule

        invalid_schedules = [
            "* * * *",  # 4 parts
            "* * * * * *",  # 6 parts
            "*",  # 1 part
            "",  # empty
        ]

        for schedule in invalid_schedules:
            valid, error = validate_cron_schedule(schedule)
            assert not valid, f"Schedule '{schedule}' should be invalid"
            assert "5 parts" in error

    def test_invalid_minute_range(self):
        """Test that invalid minute values are rejected."""
        from src.mcp.inbox_server import validate_cron_schedule

        invalid = [
            "60 * * * *",  # minute > 59
            "-1 * * * *",  # negative
        ]

        for schedule in invalid:
            valid, error = validate_cron_schedule(schedule)
            assert not valid, f"Schedule '{schedule}' should be invalid"

    def test_invalid_hour_range(self):
        """Test that invalid hour values are rejected."""
        from src.mcp.inbox_server import validate_cron_schedule

        invalid = [
            "0 24 * * *",  # hour > 23
            "0 25 * * *",
        ]

        for schedule in invalid:
            valid, error = validate_cron_schedule(schedule)
            assert not valid, f"Schedule '{schedule}' should be invalid"

    def test_invalid_day_range(self):
        """Test that invalid day values are rejected."""
        from src.mcp.inbox_server import validate_cron_schedule

        invalid = [
            "0 0 0 * *",  # day = 0 (must be 1-31)
            "0 0 32 * *",  # day > 31
        ]

        for schedule in invalid:
            valid, error = validate_cron_schedule(schedule)
            assert not valid, f"Schedule '{schedule}' should be invalid"

    def test_invalid_month_range(self):
        """Test that invalid month values are rejected."""
        from src.mcp.inbox_server import validate_cron_schedule

        invalid = [
            "0 0 * 0 *",  # month = 0 (must be 1-12)
            "0 0 * 13 *",  # month > 12
        ]

        for schedule in invalid:
            valid, error = validate_cron_schedule(schedule)
            assert not valid, f"Schedule '{schedule}' should be invalid"

    def test_invalid_weekday_range(self):
        """Test that invalid weekday values are rejected."""
        from src.mcp.inbox_server import validate_cron_schedule

        invalid = [
            "0 0 * * 8",  # weekday > 7
        ]

        for schedule in invalid:
            valid, error = validate_cron_schedule(schedule)
            assert not valid, f"Schedule '{schedule}' should be invalid"

    def test_valid_ranges(self):
        """Test valid range expressions."""
        from src.mcp.inbox_server import validate_cron_schedule

        valid = [
            "0-30 * * * *",  # minute range
            "0 9-17 * * *",  # hour range (working hours)
            "0 0 1-15 * *",  # first half of month
            "0 0 * * 1-5",  # weekdays
        ]

        for schedule in valid:
            valid_result, error = validate_cron_schedule(schedule)
            assert valid_result, f"Schedule '{schedule}' should be valid: {error}"

    def test_valid_lists(self):
        """Test valid list expressions."""
        from src.mcp.inbox_server import validate_cron_schedule

        valid = [
            "0,30 * * * *",  # 0 and 30 minutes
            "0 9,12,18 * * *",  # specific hours
            "0 0 * * 1,3,5",  # Mon, Wed, Fri
        ]

        for schedule in valid:
            valid_result, error = validate_cron_schedule(schedule)
            assert valid_result, f"Schedule '{schedule}' should be valid: {error}"

    def test_valid_step_values(self):
        """Test valid step expressions."""
        from src.mcp.inbox_server import validate_cron_schedule

        valid = [
            "*/5 * * * *",  # every 5 minutes
            "0 */2 * * *",  # every 2 hours
            "*/15 * * * *",  # every 15 minutes
        ]

        for schedule in valid:
            valid_result, error = validate_cron_schedule(schedule)
            assert valid_result, f"Schedule '{schedule}' should be valid: {error}"

    def test_invalid_step_value(self):
        """Test invalid step values."""
        from src.mcp.inbox_server import validate_cron_schedule

        invalid = [
            "*/0 * * * *",  # step of 0
            "*/-1 * * * *",  # negative step
        ]

        for schedule in invalid:
            valid, error = validate_cron_schedule(schedule)
            assert not valid, f"Schedule '{schedule}' should be invalid"


class TestValidateJobName:
    """Tests for job name validation."""

    def test_valid_job_names(self):
        """Test valid job names."""
        from src.mcp.inbox_server import validate_job_name

        valid_names = [
            "a",
            "test",
            "my-job",
            "daily-backup",
            "job-123",
            "a1b2c3",
        ]

        for name in valid_names:
            valid, error = validate_job_name(name)
            assert valid, f"Name '{name}' should be valid: {error}"

    def test_empty_name(self):
        """Test that empty name is rejected."""
        from src.mcp.inbox_server import validate_job_name

        valid, error = validate_job_name("")
        assert not valid
        assert "empty" in error.lower()

    def test_uppercase_rejected(self):
        """Test that uppercase letters are rejected."""
        from src.mcp.inbox_server import validate_job_name

        invalid = ["MyJob", "UPPERCASE", "camelCase"]

        for name in invalid:
            valid, error = validate_job_name(name)
            assert not valid, f"Name '{name}' should be invalid"

    def test_starts_with_hyphen_rejected(self):
        """Test that names starting with hyphen are rejected."""
        from src.mcp.inbox_server import validate_job_name

        valid, error = validate_job_name("-invalid")
        assert not valid

    def test_ends_with_hyphen_rejected(self):
        """Test that names ending with hyphen are rejected."""
        from src.mcp.inbox_server import validate_job_name

        valid, error = validate_job_name("invalid-")
        assert not valid

    def test_special_characters_rejected(self):
        """Test that special characters are rejected."""
        from src.mcp.inbox_server import validate_job_name

        invalid = ["job_name", "job.name", "job/name", "job name", "job@name"]

        for name in invalid:
            valid, error = validate_job_name(name)
            assert not valid, f"Name '{name}' should be invalid"

    def test_too_long_name_rejected(self):
        """Test that names over 50 chars are rejected."""
        from src.mcp.inbox_server import validate_job_name

        long_name = "a" * 51
        valid, error = validate_job_name(long_name)
        assert not valid
        assert "50 characters" in error


class TestCronToHuman:
    """Tests for cron to human-readable conversion."""

    def test_every_minute(self):
        """Test every minute conversion."""
        from src.mcp.inbox_server import cron_to_human

        result = cron_to_human("* * * * *")
        assert "every minute" in result.lower()

    def test_every_n_minutes(self):
        """Test every N minutes conversion."""
        from src.mcp.inbox_server import cron_to_human

        result = cron_to_human("*/5 * * * *")
        assert "5 minutes" in result.lower()

        result = cron_to_human("*/30 * * * *")
        assert "30 minutes" in result.lower()

    def test_every_n_hours(self):
        """Test every N hours conversion."""
        from src.mcp.inbox_server import cron_to_human

        result = cron_to_human("0 */2 * * *")
        assert "2 hours" in result.lower()

    def test_daily_at_time(self):
        """Test daily at specific time conversion."""
        from src.mcp.inbox_server import cron_to_human

        result = cron_to_human("0 9 * * *")
        assert "daily" in result.lower() or "9:00" in result

        result = cron_to_human("30 14 * * *")
        assert "14:30" in result or "14" in result

    def test_weekly_schedule(self):
        """Test weekly schedule conversion."""
        from src.mcp.inbox_server import cron_to_human

        result = cron_to_human("0 9 * * 1")
        # Should mention Monday or Mon
        assert "mon" in result.lower() or "1" in result

    def test_returns_original_for_complex(self):
        """Test that complex schedules return original."""
        from src.mcp.inbox_server import cron_to_human

        complex_schedule = "0 9 1-15 1,6 *"
        result = cron_to_human(complex_schedule)
        # Should contain the original schedule
        assert "9" in result


class TestToolListing:
    """Tests for tool listing functionality."""

    def test_list_tools_returns_all_tools(self):
        """Test that all 19 tools are listed."""
        import asyncio
        from src.mcp.inbox_server import list_tools

        tools = asyncio.run(list_tools())

        # Verify we have all expected tools
        tool_names = {tool.name for tool in tools}

        expected_tools = {
            "wait_for_messages",
            "check_inbox",
            "send_reply",
            "mark_processed",
            "list_sources",
            "get_stats",
            "list_tasks",
            "create_task",
            "update_task",
            "get_task",
            "delete_task",
            "transcribe_audio",
            "create_scheduled_job",
            "list_scheduled_jobs",
            "get_scheduled_job",
            "update_scheduled_job",
            "delete_scheduled_job",
            "check_task_outputs",
            "write_task_output",
        }

        assert expected_tools <= tool_names, f"Missing tools: {expected_tools - tool_names}"

    def test_tools_have_descriptions(self):
        """Test that all tools have descriptions."""
        import asyncio
        from src.mcp.inbox_server import list_tools

        tools = asyncio.run(list_tools())

        for tool in tools:
            assert tool.description, f"Tool {tool.name} has no description"
            assert len(tool.description) > 10, f"Tool {tool.name} has too short description"

    def test_tools_have_input_schemas(self):
        """Test that all tools have input schemas."""
        import asyncio
        from src.mcp.inbox_server import list_tools

        tools = asyncio.run(list_tools())

        for tool in tools:
            assert tool.inputSchema, f"Tool {tool.name} has no inputSchema"
            assert "type" in tool.inputSchema, f"Tool {tool.name} schema missing type"
