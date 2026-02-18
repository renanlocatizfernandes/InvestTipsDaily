"""Audio transcription using OpenAI's Whisper model."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_model = None


def _get_model():
    """Lazy-load the Whisper model (singleton)."""
    global _model
    if _model is None:
        import whisper

        model_name = os.getenv("WHISPER_MODEL", "base")
        logger.info("Loading Whisper model: %s", model_name)
        _model = whisper.load_model(model_name)
        logger.info("Whisper model '%s' loaded.", model_name)
    return _model


def transcribe_audio(file_path: str) -> str:
    """Transcribe an audio file (OGG, MP3, WAV, etc.) using Whisper.

    Args:
        file_path: Path to the audio file.

    Returns:
        Transcribed text, or empty string on failure.
    """
    try:
        if not os.path.isfile(file_path):
            logger.warning("Audio file not found: %s", file_path)
            return ""

        logger.info("Transcribing audio: %s", file_path)
        model = _get_model()
        result = model.transcribe(file_path, language="pt")
        text = result.get("text", "").strip()

        if text:
            logger.info(
                "Transcription complete (%d chars): %s",
                len(text),
                file_path,
            )
        else:
            logger.warning("Transcription returned empty text: %s", file_path)

        return text

    except Exception:
        logger.exception("Failed to transcribe audio: %s", file_path)
        return ""
