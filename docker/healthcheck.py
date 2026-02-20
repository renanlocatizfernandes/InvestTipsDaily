"""Simple health check for Docker."""
import sys
try:
    # Check if the main process module is importable
    import bot.health
    sys.exit(0)
except Exception:
    sys.exit(1)
