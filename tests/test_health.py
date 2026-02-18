"""Tests for bot health monitoring and metrics."""

import time

import pytest

from bot.health import Metrics, _format_uptime


@pytest.fixture(autouse=True)
def reset_metrics():
    """Reset the Metrics singleton before each test."""
    Metrics.reset()
    yield
    Metrics.reset()


class TestMetrics:
    """Tests for the Metrics singleton class."""

    def test_singleton(self):
        """Metrics() always returns the same instance."""
        m1 = Metrics()
        m2 = Metrics()
        assert m1 is m2

    def test_initial_status(self):
        """Fresh metrics should have zeroed counters."""
        m = Metrics()
        status = m.get_status()
        assert status["total_queries"] == 0
        assert status["avg_latency"] == 0.0
        assert status["error_count"] == 0
        assert status["last_query_seconds_ago"] is None

    def test_record_query(self):
        """record_query increments counter and tracks latency."""
        m = Metrics()
        m.record_query(1.5)
        m.record_query(2.5)
        status = m.get_status()
        assert status["total_queries"] == 2
        assert status["avg_latency"] == 2.0  # (1.5 + 2.5) / 2

    def test_record_error(self):
        """record_error increments error counter."""
        m = Metrics()
        m.record_error()
        m.record_error()
        m.record_error()
        status = m.get_status()
        assert status["error_count"] == 3

    def test_avg_latency_single_query(self):
        """Average latency with a single query equals that query's latency."""
        m = Metrics()
        m.record_query(3.14)
        status = m.get_status()
        assert status["avg_latency"] == 3.14

    def test_uptime_increases(self):
        """Uptime should increase over time."""
        m = Metrics()
        t1 = m.uptime_seconds
        time.sleep(0.05)
        t2 = m.uptime_seconds
        assert t2 > t1

    def test_uptime_in_status(self):
        """get_status includes a non-negative uptime_seconds value."""
        m = Metrics()
        time.sleep(0.05)
        status = m.get_status()
        assert status["uptime_seconds"] >= 0.01

    def test_last_query_seconds_ago(self):
        """After a query, last_query_seconds_ago should be a small positive number."""
        m = Metrics()
        m.record_query(0.1)
        time.sleep(0.05)
        status = m.get_status()
        assert status["last_query_seconds_ago"] is not None
        assert status["last_query_seconds_ago"] >= 0

    def test_start_datetime_present(self):
        """get_status includes a start_datetime ISO string."""
        m = Metrics()
        status = m.get_status()
        assert "start_datetime" in status
        assert "T" in status["start_datetime"]  # ISO format

    def test_reset_clears_counters(self):
        """reset() should zero all counters."""
        m = Metrics()
        m.record_query(1.0)
        m.record_query(2.0)
        m.record_error()
        Metrics.reset()
        status = m.get_status()
        assert status["total_queries"] == 0
        assert status["avg_latency"] == 0.0
        assert status["error_count"] == 0
        assert status["last_query_seconds_ago"] is None

    def test_mixed_operations(self):
        """Queries and errors are tracked independently."""
        m = Metrics()
        m.record_query(0.5)
        m.record_error()
        m.record_query(1.5)
        m.record_error()
        status = m.get_status()
        assert status["total_queries"] == 2
        assert status["avg_latency"] == 1.0
        assert status["error_count"] == 2


class TestFormatUptime:
    """Tests for the _format_uptime helper."""

    def test_seconds_only(self):
        assert _format_uptime(45) == "45s"

    def test_minutes(self):
        assert _format_uptime(150) == "2min"

    def test_hours_and_minutes(self):
        assert _format_uptime(9240) == "2h 34min"

    def test_days_hours_minutes(self):
        # 1 day + 3 hours + 15 minutes = 86400 + 10800 + 900 = 98100
        assert _format_uptime(98100) == "1d 3h 15min"

    def test_exact_hour(self):
        assert _format_uptime(3600) == "1h"

    def test_zero(self):
        assert _format_uptime(0) == "0s"
