FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Application code
COPY bot/ bot/
COPY rag/ rag/
COPY ingestion/ ingestion/

# Create data directories
RUN mkdir -p /app/data/chroma_db /app/data/telegram_export

CMD ["python", "-m", "bot.main"]
