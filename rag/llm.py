"""Anthropic Claude API wrapper."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone, timedelta

import anthropic
from anthropic import APIError

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
    history: list[dict] | None = None,
) -> str:
    """Send a message to Claude and return the response text.

    Args:
        system_prompt: System instructions (bot identity).
        user_message: The user's question.
        context: Retrieved context from RAG (injected into the user message).
        max_tokens: Max response length.
        history: Optional list of previous exchanges as
                 ``[{"role": "user"|"assistant", "content": "..."}]``.
                 When provided, they are prepended to the messages list
                 so Claude has conversation context.
    """
    client = _get_client()
    model = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

    # Build the user message with context
    brt = timezone(timedelta(hours=-3))
    now_brt = datetime.now(brt).strftime("%d/%m/%Y %H:%M")

    parts = []
    parts.append(f"[Data/hora atual: {now_brt} BRT]\n")
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

    # Build messages list: optional history + current user message
    messages: list[dict] = []
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": full_user_message})

    fallback_model = os.getenv("CLAUDE_FALLBACK_MODEL", "claude-haiku-4-5-20251001")

    # Estimate prompt size for logging (full message content)
    prompt_chars = sum(len(m.get("content", "")) for m in messages) + len(system_prompt)

    logger.info("Calling Claude (%s) max_tokens=%d history=%d", model, max_tokens, len(history or []))

    llm_start = time.monotonic()
    used_model = model

    try:
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
        )
    except APIError as exc:
        if fallback_model and fallback_model != model:
            logger.warning(
                "Primary model '%s' failed (%s). Retrying with fallback model '%s'...",
                model, exc, fallback_model,
            )
            used_model = fallback_model
            message = client.messages.create(
                model=fallback_model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=messages,
            )
        else:
            raise

    llm_elapsed = time.monotonic() - llm_start

    usage = message.usage
    logger.info(
        "Claude response: %d chars, tokens in=%d out=%d",
        len(message.content[0].text), usage.input_tokens, usage.output_tokens,
    )
    logger.info("LLM response in %.2fs (model=%s, ~%d prompt chars)", llm_elapsed, used_model, prompt_chars)
    return message.content[0].text
