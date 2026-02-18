"""Tests for the image analyzer module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ingestion.image_analyzer import analyze_image, SYSTEM_PROMPT, _SUPPORTED_EXTENSIONS


@pytest.fixture
def sample_jpg(tmp_path: Path) -> Path:
    """Create a minimal fake JPEG file for testing."""
    img = tmp_path / "photo_1.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0fake_jpeg_data")
    return img


@pytest.fixture
def sample_png(tmp_path: Path) -> Path:
    """Create a minimal fake PNG file for testing."""
    img = tmp_path / "photo_2.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake_png_data")
    return img


@pytest.fixture
def mock_anthropic_response():
    """Create a mock Anthropic message response."""
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="Gráfico de Bitcoin mostrando alta de 5%")]
    mock_msg.usage = MagicMock(input_tokens=100, output_tokens=15)
    return mock_msg


class TestAnalyzeImage:
    """Tests for the analyze_image function."""

    @patch("ingestion.image_analyzer._get_client")
    def test_analyze_jpg_image(self, mock_get_client, sample_jpg, mock_anthropic_response):
        """Should analyze a JPG image and return description."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_anthropic_response
        mock_get_client.return_value = mock_client

        result = analyze_image(str(sample_jpg))

        assert result == "Gráfico de Bitcoin mostrando alta de 5%"
        mock_client.messages.create.assert_called_once()

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["max_tokens"] == 200
        assert call_kwargs["system"] == SYSTEM_PROMPT

        # Verify image content block structure
        content = call_kwargs["messages"][0]["content"]
        assert len(content) == 2
        assert content[0]["type"] == "image"
        assert content[0]["source"]["type"] == "base64"
        assert content[0]["source"]["media_type"] == "image/jpeg"
        assert isinstance(content[0]["source"]["data"], str)
        assert content[1]["type"] == "text"

    @patch("ingestion.image_analyzer._get_client")
    def test_analyze_png_image(self, mock_get_client, sample_png, mock_anthropic_response):
        """Should analyze a PNG image with correct media type."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_anthropic_response
        mock_get_client.return_value = mock_client

        result = analyze_image(str(sample_png))

        assert result == "Gráfico de Bitcoin mostrando alta de 5%"
        call_kwargs = mock_client.messages.create.call_args[1]
        content = call_kwargs["messages"][0]["content"]
        assert content[0]["source"]["media_type"] == "image/png"

    def test_nonexistent_file_returns_empty(self):
        """Should return empty string for missing file."""
        result = analyze_image("/nonexistent/path/photo.jpg")
        assert result == ""

    def test_unsupported_format_returns_empty(self, tmp_path):
        """Should return empty string for unsupported image formats."""
        gif_file = tmp_path / "animation.gif"
        gif_file.write_bytes(b"GIF89a")

        result = analyze_image(str(gif_file))
        assert result == ""

    @patch("ingestion.image_analyzer._get_client")
    def test_api_error_returns_empty(self, mock_get_client, sample_jpg):
        """Should return empty string when API call fails."""
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")
        mock_get_client.return_value = mock_client

        result = analyze_image(str(sample_jpg))
        assert result == ""

    @patch("ingestion.image_analyzer._get_client")
    def test_uses_claude_model_env_var(self, mock_get_client, sample_jpg, mock_anthropic_response):
        """Should use CLAUDE_MODEL env var for model selection."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_anthropic_response
        mock_get_client.return_value = mock_client

        with patch.dict("os.environ", {"CLAUDE_MODEL": "claude-sonnet-4-20250514"}):
            analyze_image(str(sample_jpg))

        call_kwargs = mock_client.messages.create.call_args[1]
        assert call_kwargs["model"] == "claude-sonnet-4-20250514"

    @patch("ingestion.image_analyzer._get_client")
    def test_base64_encoding(self, mock_get_client, sample_jpg, mock_anthropic_response):
        """Should correctly base64-encode the image data."""
        import base64

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_anthropic_response
        mock_get_client.return_value = mock_client

        analyze_image(str(sample_jpg))

        call_kwargs = mock_client.messages.create.call_args[1]
        content = call_kwargs["messages"][0]["content"]
        encoded_data = content[0]["source"]["data"]

        # Verify it decodes back to the original file content
        decoded = base64.standard_b64decode(encoded_data)
        assert decoded == sample_jpg.read_bytes()


class TestSystemPrompt:
    """Tests for the system prompt configuration."""

    def test_prompt_is_portuguese(self):
        """System prompt should be in Portuguese."""
        assert "português" in SYSTEM_PROMPT.lower() or "descreva" in SYSTEM_PROMPT.lower()

    def test_prompt_mentions_financial(self):
        """System prompt should mention financial/crypto content."""
        assert "financeiro" in SYSTEM_PROMPT.lower()
        assert "cripto" in SYSTEM_PROMPT.lower()

    def test_prompt_mentions_meme(self):
        """System prompt should handle casual images too."""
        assert "meme" in SYSTEM_PROMPT.lower()


class TestSupportedExtensions:
    """Tests for supported image formats."""

    def test_jpg_supported(self):
        assert ".jpg" in _SUPPORTED_EXTENSIONS
        assert _SUPPORTED_EXTENSIONS[".jpg"] == "image/jpeg"

    def test_jpeg_supported(self):
        assert ".jpeg" in _SUPPORTED_EXTENSIONS
        assert _SUPPORTED_EXTENSIONS[".jpeg"] == "image/jpeg"

    def test_png_supported(self):
        assert ".png" in _SUPPORTED_EXTENSIONS
        assert _SUPPORTED_EXTENSIONS[".png"] == "image/png"
