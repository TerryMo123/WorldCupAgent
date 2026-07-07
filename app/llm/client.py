from functools import lru_cache

from openai import AsyncOpenAI, OpenAI

from app.config import settings


@lru_cache
def get_sync_openai_client() -> OpenAI:
    if not settings.dashscope_api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not configured")
    return OpenAI(
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
    )


@lru_cache
def get_async_openai_client() -> AsyncOpenAI:
    if not settings.dashscope_api_key:
        raise RuntimeError("DASHSCOPE_API_KEY is not configured")
    return AsyncOpenAI(
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
    )


def embed_texts_sync(texts: list[str]) -> list[list[float]]:
    client = get_sync_openai_client()
    response = client.embeddings.create(
        model=settings.embedding_model,
        input=texts,
    )
    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]


async def embed_text_async(text: str) -> list[float]:
    client = get_async_openai_client()
    response = await client.embeddings.create(
        model=settings.embedding_model,
        input=text,
    )
    return response.data[0].embedding
