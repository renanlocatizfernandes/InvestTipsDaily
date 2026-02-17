"""Tests for bot identity and configuration."""

from bot.identity import SYSTEM_PROMPT, ABOUT_TEXT, HELP_TEXT, BOT_NAME


def test_system_prompt_is_portuguese():
    """System prompt must be in Portuguese."""
    assert "português brasileiro" in SYSTEM_PROMPT.lower() or "pt-br" in SYSTEM_PROMPT.lower()


def test_system_prompt_mentions_creator():
    """System prompt references Renan as creator."""
    assert "Renan" in SYSTEM_PROMPT


def test_system_prompt_no_financial_advice():
    """System prompt explicitly says no financial advice."""
    assert "conselho financeiro" in SYSTEM_PROMPT.lower()


def test_bot_name():
    assert BOT_NAME == "TipsAI"


def test_about_text_has_channel():
    assert "Invest Tips Daily" in ABOUT_TEXT


def test_help_text_has_commands():
    for cmd in ["/tips", "/buscar", "/resumo", "/sobre", "/ajuda"]:
        assert cmd in HELP_TEXT
