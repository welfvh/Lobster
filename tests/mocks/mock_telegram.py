"""
Mock Telegram Bot API Server

Provides an aiohttp server that mimics the Telegram Bot API for testing.
"""

import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

from aiohttp import web


@dataclass
class MockMessage:
    """Represents a mock Telegram message."""

    message_id: int
    chat_id: int
    text: str
    from_user: dict
    date: int = field(default_factory=lambda: int(time.time()))


@dataclass
class MockUpdate:
    """Represents a mock Telegram update."""

    update_id: int
    message: Optional[MockMessage] = None


class MockTelegramServer:
    """
    Mock Telegram Bot API server.

    Usage:
        server = MockTelegramServer(port=8081)
        await server.start()

        # Queue a message for the bot to receive
        server.queue_message("Hello from test", user_id=123456)

        # Check sent messages
        sent = server.get_sent_messages()

        await server.stop()
    """

    def __init__(self, port: int = 8081, token: str = "test_token"):
        self.port = port
        self.token = token
        self.app = web.Application()
        self.runner: Optional[web.AppRunner] = None

        # Message queues
        self._incoming_queue: deque[MockUpdate] = deque()
        self._sent_messages: list[dict] = []
        self._update_id = 1
        self._message_id = 1

        # File storage (for voice messages)
        self._files: dict[str, bytes] = {}

        self._setup_routes()

    def _setup_routes(self):
        """Set up API routes."""
        self.app.router.add_post(f"/bot{self.token}/getUpdates", self._handle_get_updates)
        self.app.router.add_post(f"/bot{self.token}/sendMessage", self._handle_send_message)
        self.app.router.add_post(f"/bot{self.token}/getFile", self._handle_get_file)
        self.app.router.add_get(f"/file/bot{self.token}/{{file_path:.*}}", self._handle_download_file)
        # Catch-all for other methods
        self.app.router.add_route("*", f"/bot{self.token}/{{method}}", self._handle_other)

    async def _handle_get_updates(self, request: web.Request) -> web.Response:
        """Handle getUpdates - returns queued messages."""
        try:
            data = await request.json()
        except:
            data = {}

        timeout = data.get("timeout", 0)
        offset = data.get("offset")

        # If offset provided, remove updates before it
        if offset:
            while self._incoming_queue and self._incoming_queue[0].update_id < offset:
                self._incoming_queue.popleft()

        # Wait for messages if timeout specified and queue is empty
        if timeout > 0 and not self._incoming_queue:
            await asyncio.sleep(min(timeout, 1))  # Cap at 1s for tests

        updates = []
        while self._incoming_queue:
            update = self._incoming_queue.popleft()
            updates.append(self._serialize_update(update))

        return web.json_response({"ok": True, "result": updates})

    async def _handle_send_message(self, request: web.Request) -> web.Response:
        """Handle sendMessage - records sent messages."""
        try:
            data = await request.json()
        except:
            data = await request.post()

        chat_id = data.get("chat_id")
        text = data.get("text", "")

        if not chat_id:
            return web.json_response(
                {"ok": False, "error_code": 400, "description": "chat_id is required"},
                status=400,
            )

        # Record the sent message
        sent_msg = {
            "chat_id": chat_id,
            "text": text,
            "timestamp": time.time(),
            "message_id": self._message_id,
        }
        self._sent_messages.append(sent_msg)

        response_msg = {
            "message_id": self._message_id,
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
            "date": int(time.time()),
        }
        self._message_id += 1

        return web.json_response({"ok": True, "result": response_msg})

    async def _handle_get_file(self, request: web.Request) -> web.Response:
        """Handle getFile - returns file info."""
        try:
            data = await request.json()
        except:
            data = await request.post()

        file_id = data.get("file_id", "")

        # Check if we have this file
        if file_id in self._files:
            file_path = f"voice/{file_id}.ogg"
            return web.json_response({
                "ok": True,
                "result": {
                    "file_id": file_id,
                    "file_unique_id": f"unique_{file_id}",
                    "file_size": len(self._files[file_id]),
                    "file_path": file_path,
                }
            })

        # Return a mock file path
        return web.json_response({
            "ok": True,
            "result": {
                "file_id": file_id,
                "file_unique_id": f"unique_{file_id}",
                "file_size": 1000,
                "file_path": f"voice/{file_id}.ogg",
            }
        })

    async def _handle_download_file(self, request: web.Request) -> web.Response:
        """Handle file download."""
        file_path = request.match_info.get("file_path", "")
        file_id = file_path.replace("voice/", "").replace(".ogg", "")

        if file_id in self._files:
            return web.Response(body=self._files[file_id], content_type="audio/ogg")

        # Return empty audio data for tests
        return web.Response(body=b"\x00" * 100, content_type="audio/ogg")

    async def _handle_other(self, request: web.Request) -> web.Response:
        """Handle other API methods."""
        method = request.match_info.get("method", "unknown")
        return web.json_response({
            "ok": True,
            "result": {"method": method, "mock": True}
        })

    def _serialize_update(self, update: MockUpdate) -> dict:
        """Serialize an update to JSON-compatible dict."""
        result = {"update_id": update.update_id}
        if update.message:
            result["message"] = {
                "message_id": update.message.message_id,
                "from": update.message.from_user,
                "chat": {
                    "id": update.message.chat_id,
                    "type": "private",
                },
                "date": update.message.date,
                "text": update.message.text,
            }
        return result

    def queue_message(
        self,
        text: str,
        user_id: int = 123456,
        username: str = "testuser",
        first_name: str = "Test",
        chat_id: Optional[int] = None,
    ) -> int:
        """
        Queue a message for the bot to receive.

        Args:
            text: Message text
            user_id: Sender's user ID
            username: Sender's username
            first_name: Sender's first name
            chat_id: Chat ID (defaults to user_id for DMs)

        Returns:
            The update ID
        """
        if chat_id is None:
            chat_id = user_id

        message = MockMessage(
            message_id=self._message_id,
            chat_id=chat_id,
            text=text,
            from_user={
                "id": user_id,
                "is_bot": False,
                "first_name": first_name,
                "username": username,
            },
        )
        self._message_id += 1

        update = MockUpdate(update_id=self._update_id, message=message)
        self._update_id += 1

        self._incoming_queue.append(update)
        return update.update_id

    def queue_voice_message(
        self,
        file_id: str,
        duration: int = 5,
        user_id: int = 123456,
        username: str = "testuser",
        first_name: str = "Test",
        audio_data: bytes = b"",
    ) -> int:
        """
        Queue a voice message for the bot to receive.

        Args:
            file_id: File ID for the voice message
            duration: Audio duration in seconds
            user_id: Sender's user ID
            username: Sender's username
            first_name: Sender's first name
            audio_data: Actual audio bytes (optional)

        Returns:
            The update ID
        """
        if audio_data:
            self._files[file_id] = audio_data

        # For voice messages, we need to create a custom update
        # This is simplified - real Telegram updates have more structure
        return self.queue_message(
            text="[Voice message]",
            user_id=user_id,
            username=username,
            first_name=first_name,
        )

    def add_file(self, file_id: str, data: bytes) -> None:
        """Add a file to the mock server."""
        self._files[file_id] = data

    def get_sent_messages(self) -> list[dict]:
        """Get all messages sent via sendMessage."""
        return self._sent_messages.copy()

    def clear_sent_messages(self) -> None:
        """Clear the sent messages list."""
        self._sent_messages.clear()

    def clear_queue(self) -> None:
        """Clear the incoming message queue."""
        self._incoming_queue.clear()

    async def start(self) -> None:
        """Start the mock server."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "localhost", self.port)
        await site.start()

    async def stop(self) -> None:
        """Stop the mock server."""
        if self.runner:
            await self.runner.cleanup()
            self.runner = None

    @property
    def base_url(self) -> str:
        """Get the base URL for API calls."""
        return f"http://localhost:{self.port}/bot{self.token}"


class MockTelegramBot:
    """
    Simplified mock for python-telegram-bot's Bot class.

    Use this for unit tests that don't need a full HTTP server.
    """

    def __init__(self, token: str = "test_token"):
        self.token = token
        self._sent_messages: list[dict] = []
        self._files: dict[str, bytes] = {}

    async def send_message(
        self,
        chat_id: int,
        text: str,
        **kwargs,
    ) -> dict:
        """Mock send_message."""
        msg = {
            "chat_id": chat_id,
            "text": text,
            "timestamp": time.time(),
            **kwargs,
        }
        self._sent_messages.append(msg)
        return {"message_id": len(self._sent_messages), "text": text}

    async def get_file(self, file_id: str) -> "MockFile":
        """Mock get_file."""
        return MockFile(file_id, self._files.get(file_id, b""))

    def get_sent_messages(self) -> list[dict]:
        """Get all sent messages."""
        return self._sent_messages.copy()


class MockFile:
    """Mock telegram File object."""

    def __init__(self, file_id: str, data: bytes):
        self.file_id = file_id
        self._data = data

    async def download_to_drive(self, path) -> None:
        """Mock file download."""
        from pathlib import Path
        Path(path).write_bytes(self._data or b"\x00" * 100)
