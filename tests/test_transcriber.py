"""Tests for the audio transcriber module."""

import sys
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _reset_model():
    """Reset the singleton model before each test."""
    import ingestion.transcriber as mod
    mod._model = None
    yield
    mod._model = None


@pytest.fixture
def mock_whisper():
    """Mock the whisper module and inject it into sys.modules."""
    mock_model = MagicMock()
    mock_model.transcribe.return_value = {"text": "  Olá pessoal, boa tarde  "}

    mock_module = MagicMock()
    mock_module.load_model.return_value = mock_model

    with patch.dict(sys.modules, {"whisper": mock_module}):
        yield mock_module, mock_model


def test_transcribe_returns_text(tmp_path, mock_whisper):
    """Transcription should return stripped text from whisper result."""
    from ingestion.transcriber import transcribe_audio

    audio_file = tmp_path / "voice.ogg"
    audio_file.write_bytes(b"fake audio data")

    result = transcribe_audio(str(audio_file))

    assert result == "Olá pessoal, boa tarde"


def test_transcribe_calls_whisper_with_portuguese(tmp_path, mock_whisper):
    """Whisper should be called with language='pt' for Portuguese."""
    from ingestion.transcriber import transcribe_audio

    _, mock_model = mock_whisper
    audio_file = tmp_path / "voice.ogg"
    audio_file.write_bytes(b"fake audio data")

    transcribe_audio(str(audio_file))

    mock_model.transcribe.assert_called_once_with(str(audio_file), language="pt")


def test_transcribe_loads_model_once(tmp_path, mock_whisper):
    """Model should be loaded only once (singleton pattern)."""
    from ingestion.transcriber import transcribe_audio

    mock_mod, _ = mock_whisper
    audio_file = tmp_path / "voice.ogg"
    audio_file.write_bytes(b"fake audio data")

    transcribe_audio(str(audio_file))
    transcribe_audio(str(audio_file))

    mock_mod.load_model.assert_called_once()


def test_transcribe_uses_env_model(tmp_path, mock_whisper, monkeypatch):
    """Model name should come from WHISPER_MODEL env var."""
    from ingestion.transcriber import transcribe_audio

    mock_mod, _ = mock_whisper
    monkeypatch.setenv("WHISPER_MODEL", "large")
    audio_file = tmp_path / "voice.ogg"
    audio_file.write_bytes(b"fake audio data")

    transcribe_audio(str(audio_file))

    mock_mod.load_model.assert_called_once_with("large")


def test_transcribe_default_model(tmp_path, mock_whisper, monkeypatch):
    """Default model should be 'base' when WHISPER_MODEL is not set."""
    from ingestion.transcriber import transcribe_audio

    mock_mod, _ = mock_whisper
    monkeypatch.delenv("WHISPER_MODEL", raising=False)
    audio_file = tmp_path / "voice.ogg"
    audio_file.write_bytes(b"fake audio data")

    transcribe_audio(str(audio_file))

    mock_mod.load_model.assert_called_once_with("base")


def test_transcribe_missing_file():
    """Transcription of a non-existent file should return empty string."""
    from ingestion.transcriber import transcribe_audio

    result = transcribe_audio("/nonexistent/path/voice.ogg")
    assert result == ""


def test_transcribe_empty_result(tmp_path, mock_whisper):
    """Empty transcription result should return empty string."""
    from ingestion.transcriber import transcribe_audio

    _, mock_model = mock_whisper
    mock_model.transcribe.return_value = {"text": "   "}
    audio_file = tmp_path / "voice.ogg"
    audio_file.write_bytes(b"fake audio data")

    result = transcribe_audio(str(audio_file))

    assert result == ""


def test_transcribe_exception_returns_empty(tmp_path, mock_whisper):
    """Exceptions during transcription should be caught; return empty string."""
    from ingestion.transcriber import transcribe_audio

    _, mock_model = mock_whisper
    mock_model.transcribe.side_effect = RuntimeError("decode error")
    audio_file = tmp_path / "voice.ogg"
    audio_file.write_bytes(b"fake audio data")

    result = transcribe_audio(str(audio_file))

    assert result == ""
