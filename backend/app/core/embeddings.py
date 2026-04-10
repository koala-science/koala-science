"""
Embedding generation using Google Gemini.

Provides both sync and async functions for generating embeddings.
Used by the Temporal workflow and the backfill script.
"""
from app.core.config import settings

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMS = 768


async def generate_embedding(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float] | None:
    """
    Generate a 768-dim embedding for the given text using Gemini.
    Returns None if the API key is not configured or the call fails.
    """
    if not settings.GEMINI_API_KEY:
        print("GEMINI_API_KEY not set — skipping embedding generation")
        return None

    try:
        from google import genai

        client = genai.Client(api_key=settings.GEMINI_API_KEY)

        # Truncate to ~8000 tokens (~32000 chars) to stay within model limits
        truncated = text[:32000]

        result = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=truncated,
            config={"output_dimensionality": EMBEDDING_DIMS},
        )

        return result.embeddings[0].values

    except Exception as e:
        print(f"Embedding generation failed: {e}")
        return None


async def generate_query_embedding(query: str) -> list[float] | None:
    """Generate embedding for a search query (uses RETRIEVAL_QUERY task type)."""
    return await generate_embedding(query, task_type="RETRIEVAL_QUERY")
