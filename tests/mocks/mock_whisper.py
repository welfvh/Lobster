"""
Mock Whisper Model

Provides a mock Whisper model for testing transcription without GPU/model loading.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Union


@dataclass
class MockTranscriptionResult:
    """Mock transcription result."""

    text: str
    language: str = "en"
    segments: list = None

    def __post_init__(self):
        if self.segments is None:
            self.segments = [{"text": self.text, "start": 0.0, "end": 1.0}]


class MockWhisperModel:
    """
    Mock Whisper model for testing.

    Provides fast, deterministic transcription results without
    loading the actual model or requiring GPU.
    """

    # Predefined transcriptions by filename pattern
    DEFAULT_TRANSCRIPTIONS = {
        "hello": "Hello, how are you today?",
        "weather": "What's the weather like today?",
        "reminder": "Remind me to call mom at five PM",
        "test": "This is a test transcription",
        "empty": "",
        "long": "This is a longer transcription that spans multiple sentences. "
               "It demonstrates the model's ability to handle extended audio. "
               "The quick brown fox jumps over the lazy dog.",
    }

    def __init__(self, model_name: str = "small"):
        self.model_name = model_name
        self._custom_transcriptions: Dict[str, str] = {}
        self._call_count = 0
        self._last_file: Optional[str] = None
        self._simulate_delay = 0.0

    def transcribe(
        self,
        audio: Union[str, Path],
        language: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """
        Mock transcription.

        Args:
            audio: Path to audio file
            language: Language code (ignored in mock)
            **kwargs: Other whisper options (ignored)

        Returns:
            Dict with 'text' key containing transcription
        """
        self._call_count += 1
        audio_path = str(audio)
        self._last_file = audio_path

        # Simulate processing delay if configured
        if self._simulate_delay > 0:
            time.sleep(self._simulate_delay)

        # Check for custom transcription first
        for pattern, text in self._custom_transcriptions.items():
            if pattern in audio_path:
                return {"text": text, "language": language or "en"}

        # Check default transcriptions
        for pattern, text in self.DEFAULT_TRANSCRIPTIONS.items():
            if pattern in audio_path.lower():
                return {"text": text, "language": language or "en"}

        # Default fallback
        return {
            "text": f"Mock transcription for: {Path(audio_path).name}",
            "language": language or "en",
        }

    def set_transcription(self, pattern: str, text: str) -> None:
        """
        Set a custom transcription for files matching pattern.

        Args:
            pattern: String pattern to match in filename
            text: Transcription text to return
        """
        self._custom_transcriptions[pattern] = text

    def clear_custom_transcriptions(self) -> None:
        """Clear all custom transcriptions."""
        self._custom_transcriptions.clear()

    def set_delay(self, seconds: float) -> None:
        """Set simulated processing delay."""
        self._simulate_delay = seconds

    @property
    def call_count(self) -> int:
        """Number of times transcribe was called."""
        return self._call_count

    @property
    def last_file(self) -> Optional[str]:
        """Path of the last transcribed file."""
        return self._last_file

    def reset_stats(self) -> None:
        """Reset call statistics."""
        self._call_count = 0
        self._last_file = None


def mock_load_model(model_name: str = "small") -> MockWhisperModel:
    """
    Mock replacement for whisper.load_model().

    Use with unittest.mock.patch:
        with patch('whisper.load_model', mock_load_model):
            ...
    """
    return MockWhisperModel(model_name)


# Global instance for shared state in tests
_global_mock: Optional[MockWhisperModel] = None


def get_mock_model() -> MockWhisperModel:
    """Get the global mock model instance."""
    global _global_mock
    if _global_mock is None:
        _global_mock = MockWhisperModel()
    return _global_mock


def reset_mock_model() -> None:
    """Reset the global mock model."""
    global _global_mock
    _global_mock = None
