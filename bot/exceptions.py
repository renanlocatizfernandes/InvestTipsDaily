"""Domain-specific exceptions for TipsAI bot."""


class TipsAIError(Exception):
    """Base exception for all TipsAI errors."""
    pass


class RateLimitExceededError(TipsAIError):
    """User exceeded rate limit."""
    def __init__(self, wait_seconds: float):
        self.wait_seconds = wait_seconds
        super().__init__(f"Rate limit exceeded. Wait {wait_seconds:.0f}s")


class RAGError(TipsAIError):
    """Error in RAG pipeline (search or generation)."""
    pass


class EmbeddingError(TipsAIError):
    """Error generating embeddings."""
    pass


class LLMError(TipsAIError):
    """Error calling the LLM API."""
    pass


class IngestionError(TipsAIError):
    """Error during message ingestion."""
    pass


class SearchError(TipsAIError):
    """Error during web search."""
    pass
