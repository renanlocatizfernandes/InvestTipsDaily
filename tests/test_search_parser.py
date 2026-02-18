"""Tests for rag.search_parser — query filter extraction."""

from rag.search_parser import parse_search_query


class TestParseSearchQuery:
    """Tests for parse_search_query()."""

    # ------------------------------------------------------------------
    # Basic filter extraction
    # ------------------------------------------------------------------

    def test_author_and_text(self):
        result = parse_search_query("autor:Renan bitcoin")
        assert result["text"] == "bitcoin"
        assert result["author"] == "Renan"
        assert result["date_from"] is None
        assert result["date_to"] is None

    def test_date_from_and_text(self):
        result = parse_search_query("de:2024-08-01 CoinTech2U")
        assert result["text"] == "CoinTech2U"
        assert result["date_from"] == "2024-08-01"
        assert result["author"] is None
        assert result["date_to"] is None

    def test_date_to_and_text(self):
        result = parse_search_query("ate:2024-09-30 rendimento")
        assert result["text"] == "rendimento"
        assert result["date_to"] == "2024-09-30"
        assert result["author"] is None
        assert result["date_from"] is None

    # ------------------------------------------------------------------
    # Combined filters
    # ------------------------------------------------------------------

    def test_all_filters(self):
        result = parse_search_query("autor:Renan bitcoin de:2024-08-01 ate:2024-09-30")
        assert result["text"] == "bitcoin"
        assert result["author"] == "Renan"
        assert result["date_from"] == "2024-08-01"
        assert result["date_to"] == "2024-09-30"

    def test_example_from_spec(self):
        """The exact example from the task specification."""
        result = parse_search_query("autor:Renan bitcoin de:2024-08-01")
        assert result == {
            "text": "bitcoin",
            "author": "Renan",
            "date_from": "2024-08-01",
            "date_to": None,
        }

    def test_author_and_date_range_no_text(self):
        result = parse_search_query("autor:Ana de:2024-08-01 ate:2024-08-31")
        assert result["text"] == ""
        assert result["author"] == "Ana"
        assert result["date_from"] == "2024-08-01"
        assert result["date_to"] == "2024-08-31"

    # ------------------------------------------------------------------
    # No filters — plain semantic search
    # ------------------------------------------------------------------

    def test_no_filters(self):
        result = parse_search_query("CoinTech2U rendimento")
        assert result["text"] == "CoinTech2U rendimento"
        assert result["author"] is None
        assert result["date_from"] is None
        assert result["date_to"] is None

    def test_plain_single_word(self):
        result = parse_search_query("staking")
        assert result["text"] == "staking"
        assert result["author"] is None

    # ------------------------------------------------------------------
    # Only filters, no search text
    # ------------------------------------------------------------------

    def test_only_author(self):
        result = parse_search_query("autor:Carlos")
        assert result["text"] == ""
        assert result["author"] == "Carlos"

    def test_only_date_range(self):
        result = parse_search_query("de:2024-09-01 ate:2024-09-15")
        assert result["text"] == ""
        assert result["date_from"] == "2024-09-01"
        assert result["date_to"] == "2024-09-15"

    # ------------------------------------------------------------------
    # Case insensitivity of filter keywords
    # ------------------------------------------------------------------

    def test_uppercase_filter_keywords(self):
        result = parse_search_query("AUTOR:Renan DE:2024-08-01 ATE:2024-09-30 bitcoin")
        assert result["author"] == "Renan"
        assert result["date_from"] == "2024-08-01"
        assert result["date_to"] == "2024-09-30"
        assert result["text"] == "bitcoin"

    def test_mixed_case_filter_keywords(self):
        result = parse_search_query("Autor:Joao Ate:2024-12-31 criptomoedas")
        assert result["author"] == "Joao"
        assert result["date_to"] == "2024-12-31"
        assert result["text"] == "criptomoedas"

    # ------------------------------------------------------------------
    # Filter order independence
    # ------------------------------------------------------------------

    def test_filters_at_end(self):
        result = parse_search_query("bitcoin autor:Renan de:2024-08-01")
        assert result["text"] == "bitcoin"
        assert result["author"] == "Renan"
        assert result["date_from"] == "2024-08-01"

    def test_filters_in_middle(self):
        result = parse_search_query("bitcoin autor:Renan rendimento")
        assert result["text"] == "bitcoin rendimento"
        assert result["author"] == "Renan"

    def test_filters_scattered(self):
        result = parse_search_query("de:2024-08-01 bitcoin autor:Renan ate:2024-09-30")
        assert result["text"] == "bitcoin"
        assert result["author"] == "Renan"
        assert result["date_from"] == "2024-08-01"
        assert result["date_to"] == "2024-09-30"

    # ------------------------------------------------------------------
    # Whitespace handling
    # ------------------------------------------------------------------

    def test_extra_whitespace(self):
        result = parse_search_query("  autor:Renan   bitcoin   de:2024-08-01  ")
        assert result["text"] == "bitcoin"
        assert result["author"] == "Renan"
        assert result["date_from"] == "2024-08-01"

    def test_empty_query(self):
        result = parse_search_query("")
        assert result["text"] == ""
        assert result["author"] is None
        assert result["date_from"] is None
        assert result["date_to"] is None

    def test_whitespace_only(self):
        result = parse_search_query("   ")
        assert result["text"] == ""
        assert result["author"] is None

    # ------------------------------------------------------------------
    # Multi-word search text preserved
    # ------------------------------------------------------------------

    def test_multi_word_text(self):
        result = parse_search_query("autor:Renan como funciona o staking de ethereum")
        assert result["text"] == "como funciona o staking de ethereum"
        assert result["author"] == "Renan"
