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
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Create non-root user
RUN groupadd --gid 1001 appuser && \
    useradd --uid 1001 --gid 1001 --create-home --shell /bin/sh appuser

# HuggingFace/sentence-transformers cache inside container
ENV HF_HOME=/app/data/model_cache
ENV SENTENCE_TRANSFORMERS_HOME=/app/data/model_cache

# Create data directories and set ownership
RUN mkdir -p /app/data/chroma_db /app/data/telegram_export /app/data/model_cache && \
    chown -R appuser:appuser /app/data

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD ["python", "/app/healthcheck.py"]

# Entrypoint fixes volume permissions then drops to non-root user
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "-m", "bot.main"]
