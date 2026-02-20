FROM python:3.12-slim

# Labels for metadata
LABEL maintainer="renanlocatizfernandes"
LABEL description="InvestTipsDaily - Telegram group chat intelligence bot with RAG pipeline"

WORKDIR /app

# System dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Application code
COPY bot/ bot/
COPY rag/ rag/
COPY ingestion/ ingestion/
COPY docker/healthcheck.py /app/healthcheck.py

# Create non-root user
RUN groupadd --gid 1001 appuser && \
    useradd --uid 1001 --gid 1001 --no-create-home --shell /bin/false appuser

# Create data directories and set ownership
RUN mkdir -p /app/data/chroma_db /app/data/telegram_export && \
    chown -R appuser:appuser /app/data

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD ["python", "/app/healthcheck.py"]

CMD ["python", "-m", "bot.main"]
