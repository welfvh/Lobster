#!/usr/bin/env python3
"""
Mock Claude CLI

Provides a mock Claude CLI executable for testing the daemon and scheduled tasks.

Usage as a module:
    from tests.mocks.mock_claude_cli import MockClaudeCLI
    mock = MockClaudeCLI()
    mock.set_response("Hello from Claude")

Usage as an executable (install to PATH):
    python tests/mocks/mock_claude_cli.py install /tmp/mock-bin
    export PATH=/tmp/mock-bin:$PATH
    # Now 'claude' command will use this mock

Environment variables control behavior:
    MOCK_CLAUDE_MODE: default, error, timeout, mcp_call
    MOCK_CLAUDE_RESPONSE: Custom response text
    MOCK_CLAUDE_LOG_FILE: Path to log invocations (default: /tmp/mock_claude_invocations.json)
"""

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class MockInvocation:
    """Record of a mock CLI invocation."""

    timestamp: float
    args: list[str]
    mode: str
    response: str
    exit_code: int
    working_dir: str


class MockClaudeCLI:
    """
    Mock Claude CLI for testing.

    Provides programmatic control over CLI behavior for unit tests.
    """

    def __init__(self, log_file: Optional[Path] = None):
        self.log_file = log_file or Path("/tmp/mock_claude_invocations.json")
        self._response = "Mock Claude response"
        self._exit_code = 0
        self._mode = "default"
        self._invocations: list[MockInvocation] = []

    def set_response(self, response: str) -> None:
        """Set the response text."""
        self._response = response

    def set_exit_code(self, code: int) -> None:
        """Set the exit code."""
        self._exit_code = code

    def set_mode(self, mode: str) -> None:
        """
        Set the mock mode.

        Modes:
            - default: Return configured response
            - error: Return error exit code
            - timeout: Simulate timeout (sleep then exit)
            - mcp_call: Simulate MCP tool call output
        """
        self._mode = mode

    def simulate_invocation(self, args: list[str]) -> tuple[str, str, int]:
        """
        Simulate a CLI invocation.

        Args:
            args: Command line arguments

        Returns:
            Tuple of (stdout, stderr, exit_code)
        """
        invocation = MockInvocation(
            timestamp=time.time(),
            args=args,
            mode=self._mode,
            response=self._response,
            exit_code=self._exit_code,
            working_dir=os.getcwd(),
        )
        self._invocations.append(invocation)
        self._save_invocations()

        if self._mode == "error":
            return "", "Error: Mock error mode", 1

        if self._mode == "timeout":
            time.sleep(5)  # Simulate long-running process
            return "", "Timeout", 1

        if self._mode == "mcp_call":
            # Simulate output that includes MCP tool calls
            mcp_output = """
Processing messages...
[Tool Call] check_inbox()
[Tool Result] 2 messages found
[Tool Call] send_reply(chat_id=123456, text="Hello!")
[Tool Result] Reply sent
[Tool Call] mark_processed(message_id="msg_1")
[Tool Result] Message marked processed

All messages processed.
"""
            return mcp_output, "", 0

        return self._response, "", self._exit_code

    def get_invocations(self) -> list[MockInvocation]:
        """Get all recorded invocations."""
        return self._invocations.copy()

    def clear_invocations(self) -> None:
        """Clear recorded invocations."""
        self._invocations.clear()
        if self.log_file.exists():
            self.log_file.unlink()

    def _save_invocations(self) -> None:
        """Save invocations to log file."""
        data = [
            {
                "timestamp": inv.timestamp,
                "args": inv.args,
                "mode": inv.mode,
                "response": inv.response[:100],  # Truncate
                "exit_code": inv.exit_code,
                "working_dir": inv.working_dir,
            }
            for inv in self._invocations
        ]
        self.log_file.write_text(json.dumps(data, indent=2))


def install_mock_claude(bin_dir: Path) -> Path:
    """
    Install the mock claude executable to a directory.

    Args:
        bin_dir: Directory to install to

    Returns:
        Path to the installed executable
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    claude_path = bin_dir / "claude"

    # Create the mock executable script
    script = f'''#!/usr/bin/env python3
"""Mock Claude CLI - Auto-generated"""
import sys
sys.path.insert(0, "{Path(__file__).parent.parent}")
from tests.mocks.mock_claude_cli import main
main()
'''

    claude_path.write_text(script)
    claude_path.chmod(0o755)

    return claude_path


def main():
    """
    Main entry point when run as executable.

    Reads configuration from environment variables.
    """
    mode = os.environ.get("MOCK_CLAUDE_MODE", "default")
    response = os.environ.get("MOCK_CLAUDE_RESPONSE", "Mock Claude response")
    log_file = Path(os.environ.get("MOCK_CLAUDE_LOG_FILE", "/tmp/mock_claude_invocations.json"))

    mock = MockClaudeCLI(log_file=log_file)
    mock.set_mode(mode)
    mock.set_response(response)

    stdout, stderr, exit_code = mock.simulate_invocation(sys.argv[1:])

    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)

    sys.exit(exit_code)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "install":
        # Install mode
        if len(sys.argv) < 3:
            print("Usage: python mock_claude_cli.py install <bin_dir>")
            sys.exit(1)
        bin_dir = Path(sys.argv[2])
        path = install_mock_claude(bin_dir)
        print(f"Installed mock claude to: {path}")
    else:
        # Run as mock CLI
        main()
