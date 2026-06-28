"""结构化日志与 chat_turn 可观测性辅助。"""
from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable

from app.models import User
from app.services.api_key import resolve_api_key
from app.services.context_limits import chars_to_estimated_tokens
from app.services.deepseek import DeepSeekError, chat_completion, collect_stream

logger = logging.getLogger("novflow.agent")


def log_structured(event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    try:
        logger.info(json.dumps(payload, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        logger.info("%s %s", event, fields)


@contextmanager
def timed_operation(event: str, **fields: Any):
    start = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        log_structured(event, duration_ms=duration_ms, **fields)


@dataclass
class LLMCallTracker:
    """记录单轮 chat_turn 内的 LLM 调用。"""

    calls: list[dict[str, Any]] = field(default_factory=list)

    def _estimate_tokens(self, messages: list[dict], response: str = "") -> int:
        chars = sum(len(str(m.get("content") or "")) for m in messages) + len(response)
        return chars_to_estimated_tokens(chars)

    def record(self, purpose: str, messages: list[dict], response: str = "", **extra: Any) -> None:
        self.calls.append(
            {
                "purpose": purpose,
                "estimated_tokens": self._estimate_tokens(messages, response),
                **extra,
            }
        )

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def estimated_tokens(self) -> int:
        return sum(int(c.get("estimated_tokens") or 0) for c in self.calls)

    def to_meta(self, execution_mode: str | None = None) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "call_count": self.call_count,
            "estimated_tokens": self.estimated_tokens,
            "llm_calls": list(self.calls),
        }
        if execution_mode:
            meta["execution_mode"] = execution_mode
        return meta


async def tracked_chat(
    tracker: LLMCallTracker,
    user: User,
    messages: list[dict],
    *,
    purpose: str,
    temperature: float = 0.75,
    max_tokens: int = 4096,
    json_object: bool = False,
) -> str:
    key = resolve_api_key(user)
    if not key:
        raise DeepSeekError("请先在「设置」中配置 DeepSeek API Key")
    with timed_operation("llm_call", purpose=purpose, json_object=json_object):
        raw = await chat_completion(
            messages,
            api_key=key,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            json_object=json_object,
        )
    tracker.record(purpose, messages, str(raw or ""))
    return str(raw or "")


async def tracked_chat_stream(
    tracker: LLMCallTracker,
    user: User,
    messages: list[dict],
    *,
    purpose: str,
    temperature: float = 0.75,
    max_tokens: int = 4096,
    json_object: bool = False,
    on_token: Callable[[str], None] | None = None,
) -> str:
    key = resolve_api_key(user)
    if not key:
        raise DeepSeekError("请先在「设置」中配置 DeepSeek API Key")
    with timed_operation("llm_call_stream", purpose=purpose, json_object=json_object):
        stream = await chat_completion(
            messages,
            api_key=key,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            json_object=json_object,
        )
        assert hasattr(stream, "__aiter__")
        parts: list[str] = []
        async for token in stream:  # type: ignore[union-attr]
            parts.append(token)
            if on_token:
                on_token(token)
        raw = "".join(parts)
    tracker.record(purpose, messages, raw, streamed=True)
    return raw


StreamEmit = Callable[[str, dict[str, Any]], None]
