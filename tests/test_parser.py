"""Tests for the Telegram HTML parser."""

from datetime import datetime
from pathlib import Path
from textwrap import dedent

import pytest

from ingestion.parser import (
    TelegramMessage,
    parse_html_file,
)


@pytest.fixture
def sample_html(tmp_path: Path) -> Path:
    """Create a minimal Telegram export HTML file for testing."""
    html = dedent("""\
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"/><title>Test</title></head>
    <body>
    <div class="page_wrap">
    <div class="page_body chat_page">
    <div class="history">

    <div class="message service" id="message1">
      <div class="body details">Group created</div>
    </div>

    <div class="message default clearfix" id="message5">
      <div class="pull_left userpic_wrap">
        <div class="userpic userpic6" style="width: 42px; height: 42px">
          <div class="initials" style="line-height: 42px">RN</div>
        </div>
      </div>
      <div class="body">
        <div class="pull_right date details" title="17.08.2024 14:34:09 UTC-03:00">14:34</div>
        <div class="from_name">Renan</div>
        <div class="text">Boa tarde pessoal!</div>
      </div>
    </div>

    <div class="message default clearfix joined" id="message6">
      <div class="body">
        <div class="pull_right date details" title="17.08.2024 14:35:00 UTC-03:00">14:35</div>
        <div class="text">Segundo mensagem do Renan</div>
      </div>
    </div>

    <div class="message default clearfix" id="message7">
      <div class="pull_left userpic_wrap">
        <div class="userpic userpic5" style="width: 42px; height: 42px">
          <div class="initials" style="line-height: 42px">ZZ</div>
        </div>
      </div>
      <div class="body">
        <div class="pull_right date details" title="18.08.2024 22:09:29 UTC-03:00">22:09</div>
        <div class="from_name">Zimzum</div>
        <div class="reply_to details">
          In reply to <a href="#go_to_message5" onclick="return GoToMessage(5)">this message</a>
        </div>
        <div class="text">Boa noite!</div>
      </div>
    </div>

    <div class="message default clearfix" id="message8">
      <div class="pull_left userpic_wrap">
        <div class="userpic userpic5" style="width: 42px; height: 42px">
          <div class="initials" style="line-height: 42px">CC</div>
        </div>
      </div>
      <div class="body">
        <div class="pull_right date details" title="19.08.2024 10:00:00 UTC-03:00">10:00</div>
        <div class="from_name">Caio</div>
        <div class="media_wrap clearfix">
          <a class="photo_wrap clearfix pull_left" href="photos/photo_1.jpg">
            <img class="photo" src="photos/photo_1_thumb.jpg" style="width: 100px; height: 100px"/>
          </a>
        </div>
        <div class="text">Olha essa foto</div>
      </div>
    </div>

    <div class="message default clearfix" id="message9">
      <div class="pull_left userpic_wrap">
        <div class="userpic userpic5" style="width: 42px; height: 42px">
          <div class="initials" style="line-height: 42px">ZZ</div>
        </div>
      </div>
      <div class="body">
        <div class="pull_right date details" title="19.08.2024 11:00:00 UTC-03:00">11:00</div>
        <div class="from_name">Zimzum</div>
        <div class="pull_left forwarded userpic_wrap">
          <div class="userpic userpic5" style="width: 42px; height: 42px">
            <div class="initials" style="line-height: 42px">XX</div>
          </div>
        </div>
        <div class="forwarded body">
          <div class="from_name">Original Author<span class="date details" title="18.08.2024 08:00:00 UTC-03:00"> 18.08.2024 08:00:00</span></div>
          <div class="text">Mensagem encaminhada</div>
        </div>
      </div>
    </div>

    </div>
    </div>
    </div>
    </body>
    </html>
    """)
    filepath = tmp_path / "messages.html"
    filepath.write_text(html, encoding="utf-8")
    return filepath


def test_parse_basic_message(sample_html: Path):
    """Test parsing a basic message with author, timestamp, text."""
    messages = parse_html_file(sample_html)
    msg = messages[0]  # message5
    assert msg.id == 5
    assert msg.author == "Renan"
    assert msg.timestamp == datetime(2024, 8, 17, 14, 34, 9)
    assert msg.text == "Boa tarde pessoal!"
    assert msg.reply_to_id is None
    assert msg.media_type is None
    assert not msg.is_forwarded


def test_parse_joined_inherits_author(sample_html: Path):
    """Joined messages should inherit author from previous message."""
    messages = parse_html_file(sample_html)
    msg = messages[1]  # message6 (joined)
    assert msg.id == 6
    assert msg.author == "Renan"
    assert msg.text == "Segundo mensagem do Renan"


def test_parse_reply_to(sample_html: Path):
    """Test parsing reply_to reference."""
    messages = parse_html_file(sample_html)
    msg = messages[2]  # message7
    assert msg.id == 7
    assert msg.author == "Zimzum"
    assert msg.reply_to_id == 5
    assert msg.text == "Boa noite!"


def test_parse_media(sample_html: Path):
    """Test parsing media (photo) attachment."""
    messages = parse_html_file(sample_html)
    msg = messages[3]  # message8
    assert msg.id == 8
    assert msg.media_type == "photo"
    assert msg.media_path == "photos/photo_1.jpg"
    assert msg.text == "Olha essa foto"


def test_parse_forwarded(sample_html: Path):
    """Test parsing forwarded messages."""
    messages = parse_html_file(sample_html)
    msg = messages[4]  # message9
    assert msg.id == 9
    assert msg.is_forwarded
    assert msg.forwarded_from == "Original Author"


def test_skips_service_messages(sample_html: Path):
    """Service messages (group events) should be skipped."""
    messages = parse_html_file(sample_html)
    ids = [m.id for m in messages]
    assert 1 not in ids  # service message


def test_parse_message_count(sample_html: Path):
    """Should parse all 5 default messages."""
    messages = parse_html_file(sample_html)
    assert len(messages) == 5


def test_parse_all_exports(sample_html: Path):
    """Test parse_all_exports scans directory for messages*.html."""
    from ingestion.parser import parse_all_exports

    messages = parse_all_exports(sample_html.parent)
    assert len(messages) == 5
