"""Anthropic Claude API wrapper."""

from __future__ import annotations

import logging
import os

import anthropic

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Lazy-initialize the Anthropic client."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var
    return _client


def generate_response(
    system_prompt: str,
    user_message: str,
    context: str = "",
    max_tokens: int = 512,
) -> str:
    """Send a message to Claude and return the response text.

    Args:
        system_prompt: System instructions (bot identity).
        user_message: The user's question.
        context: Retrieved context from RAG (injected into the user message).
        max_tokens: Max response length.
    """
    client = _get_client()
    model = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

    # Build the user message with context
    parts = []
    if context:
        parts.append(
            "Contexto relevante:\n\n"
            f"{context}\n\n---\n"
        )
    parts.append(
        f"Pergunta: {user_message}\n\n"
        "Responda de forma concisa e direta. "
        "Adapte o tamanho ao que a pergunta exige — sem enrolação."
    )
    full_user_message = "\n".join(parts)

    logger.info("Calling Claude (%s) max_tokens=%d", model, max_tokens)

    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": full_user_message}],
    )

    usage = message.usage
    logger.info(
        "Claude response: %d chars, tokens in=%d out=%d",
        len(message.content[0].text), usage.input_tokens, usage.output_tokens,
    )
    return message.content[0].text
