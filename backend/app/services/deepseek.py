from __future__ import annotations

import json
from typing import AsyncIterator, Callable

import httpx

from app.config import settings


class DeepSeekError(Exception):
    pass


async def chat_completion(
    messages: list[dict],
    *,
    api_key: str | None = None,
    temperature: float = 0.8,
    max_tokens: int = 4096,
    stream: bool = False,
    json_object: bool = False,
) -> str | AsyncIterator[str]:
    key = api_key or settings.deepseek_api_key
    if not key:
        raise DeepSeekError("未配置 DeepSeek API Key，请在「设置」中填写")

    url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload: dict = {
        "model": settings.deepseek_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream,
    }
    if json_object:
        payload["response_format"] = {"type": "json_object"}

    if not stream:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                raise DeepSeekError(f"DeepSeek API 错误: {resp.status_code} {resp.text[:200]}")
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    client = httpx.AsyncClient(timeout=120.0)

    async def _stream() -> AsyncIterator[str]:
        try:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise DeepSeekError(f"DeepSeek API 错误: {resp.status_code} {body[:200]!r}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    chunk = line[6:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        obj = json.loads(chunk)
                        delta = obj["choices"][0].get("delta", {})
                        if text := delta.get("content"):
                            yield text
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
        finally:
            await client.aclose()

    return _stream()


async def collect_stream(stream: AsyncIterator[str]) -> str:
    parts: list[str] = []
    async for token in stream:
        parts.append(token)
    return "".join(parts)


async def chat_completion_stream(
    messages: list[dict],
    *,
    api_key: str | None = None,
    temperature: float = 0.8,
    max_tokens: int = 4096,
    on_chunk: Callable[[str], None] | None = None,
) -> str:
    """流式调用并返回完整文本（供 generation 模块使用）。"""
    stream = await chat_completion(
        messages,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    parts: list[str] = []
    async for token in stream:
        parts.append(token)
        if on_chunk:
            on_chunk(token)
    return "".join(parts)
