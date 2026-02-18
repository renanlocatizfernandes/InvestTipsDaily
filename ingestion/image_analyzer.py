"""Image analysis using Claude Vision API."""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None

SYSTEM_PROMPT = (
    "Descreva esta imagem de forma concisa em português. "
    "Se for um gráfico financeiro, screenshot de cotação, ou conteúdo "
    "relacionado a investimentos/cripto, extraia os dados relevantes. "
    "Se for um meme ou imagem casual, descreva brevemente."
)

_SUPPORTED_EXTENSIONS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


def _get_client() -> anthropic.Anthropic:
    """Lazy-initialize the Anthropic client (singleton)."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var
    return _client


def analyze_image(file_path: str) -> str:
    """Analyze an image using Claude Vision and return a text description.

    Args:
        file_path: Path to the image file (JPG or PNG).

    Returns:
        Text description of the image, or empty string on failure.
    """
    try:
        path = Path(file_path)

        if not path.is_file():
            logger.warning("Image file not found: %s", file_path)
            return ""

        ext = path.suffix.lower()
        media_type = _SUPPORTED_EXTENSIONS.get(ext)
        if media_type is None:
            logger.warning("Unsupported image format '%s': %s", ext, file_path)
            return ""

        logger.info("Analyzing image: %s", file_path)

        image_data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")

        client = _get_client()
        model = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

        message = client.messages.create(
            model=model,
            max_tokens=200,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Descreva esta imagem.",
                        },
                    ],
                }
            ],
        )

        description = message.content[0].text.strip()
        usage = message.usage
        logger.info(
            "Image analysis complete (%d chars, tokens in=%d out=%d): %s",
            len(description),
            usage.input_tokens,
            usage.output_tokens,
            file_path,
        )
        return description

    except Exception:
        logger.exception("Failed to analyze image: %s", file_path)
        return ""
