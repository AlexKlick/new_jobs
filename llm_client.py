"""
vLLM Nanbeige Client with Circuit Breaker

Provides async LLM client for vLLM Nanbeige with circuit breaker pattern.
Reused from vllm-nanbeige meeting_system/llm.py pattern.

Usage:
    client = VLLMClient(
        base_url="http://localhost:8000/v1",
        model="Nanbeige/Nanbeige4.1-3B",
    )
    response = await client.complete_text("Hello", context=[...])
"""

from __future__ import annotations

import asyncio
import logging
import os
import time as _time
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

_logger = logging.getLogger(__name__)

_CB_CLOSED = 0
_CB_HALF_OPEN = 1
_CB_OPEN = 2


class VLLMCircuitOpenError(Exception):
    """Raised when the vLLM circuit breaker is open.

    Indicates fast-fail: do not wait for vLLM timeout.
    """
    pass


class VLLMClient:
    """Async vLLM client with circuit breaker for Nanbeige LLM."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout_s: int = 180,
        failure_threshold: int = 3,
        recovery_timeout_s: int = 30,
    ):
        self.base_url = (base_url or os.environ.get("VLLM_BASE_URL", "http://localhost:8000")).rstrip("/")
        self.model = model or os.environ.get("LLM_MODEL", "Nanbeige/Nanbeige4.1-3B")
        self.timeout_s = timeout_s
        self._client = AsyncOpenAI(
            base_url=f"{self.base_url}/v1",
            api_key="placeholder",  # vLLM doesn't need real auth
            timeout=timeout_s,
        )
        self._failure_count: int = 0
        self._circuit_open_since: float | None = None
        self._circuit_lock = asyncio.Lock()
        self._failure_threshold: int = failure_threshold
        self._recovery_timeout_s: int = recovery_timeout_s
        self._circuit_state: int = _CB_CLOSED  # 0=closed, 1=half-open, 2=open

    def _is_circuit_open(self) -> bool:
        """Return True if circuit is open (fast-fail mode).

        After recovery_timeout_s, returns False to allow a probe request (half-open).
        Transitions state from OPEN to HALF_OPEN on first probe call.
        """
        if self._circuit_open_since is None:
            return False
        if _time.monotonic() - self._circuit_open_since >= self._recovery_timeout_s:
            # Recovery timeout reached -- allow probe request (half-open)
            if self._circuit_state == _CB_OPEN:
                self._circuit_state = _CB_HALF_OPEN
            return False
        return True

    async def stream_chat(
        self,
        user_text: str,
        context: list[dict[str, str]] | None = None,
        max_tokens: int = 512,
    ) -> AsyncIterator[str]:
        """Stream chat response from vLLM."""
        # Build messages
        messages = self._build_messages(user_text, context)

        # Fast-fail if circuit is open (before acquiring any resource)
        async with self._circuit_lock:
            if self._is_circuit_open():
                raise VLLMCircuitOpenError("vLLM circuit breaker open")

        try:
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.7,
                stream=True,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

            # Success -- reset failure count, close circuit if it was half-open
            async with self._circuit_lock:
                if self._circuit_state == _CB_HALF_OPEN:
                    _logger.info("vLLM circuit breaker closed after successful recovery")
                self._failure_count = 0
                self._circuit_open_since = None
                self._circuit_state = _CB_CLOSED
        except Exception as exc:
            await self._record_failure(exc)
            raise

    async def complete_text(
        self,
        user_text: str,
        context: list[dict[str, str]] | None = None,
        max_tokens: int = 512,
    ) -> str:
        """Get complete text response from vLLM."""
        messages = self._build_messages(user_text, context)

        # Fast-fail if circuit is open
        async with self._circuit_lock:
            if self._is_circuit_open():
                raise VLLMCircuitOpenError("vLLM circuit breaker open")

        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.7,
                stream=False,
            )
            content = response.choices[0].message.content or ""

            # Success -- reset failure count
            async with self._circuit_lock:
                if self._circuit_state == _CB_HALF_OPEN:
                    _logger.info("vLLM circuit breaker closed after successful recovery")
                self._failure_count = 0
                self._circuit_open_since = None
                self._circuit_state = _CB_CLOSED

            return content
        except Exception as exc:
            await self._record_failure(exc)
            raise

    async def health(self) -> bool:
        """Check if vLLM is healthy."""
        try:
            # Use a simple models list call to check health
            await self._client.models.list()
            return True
        except Exception:
            return False

    async def aclose(self) -> None:
        """Close the client."""
        await self._client.close()

    def _build_messages(
        self, user_text: str, context: list[dict[str, str]] | None
    ) -> list[dict[str, str]]:
        """Build message list from user text and context."""
        messages = []
        if context:
            for msg in context:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_text})
        return messages

    async def _record_failure(self, exc: Exception) -> None:
        """Record a failure, opening the circuit if threshold is reached."""
        async with self._circuit_lock:
            self._failure_count += 1
            if self._failure_count >= self._failure_threshold:
                self._circuit_open_since = _time.monotonic()
                if self._circuit_state != _CB_OPEN:
                    self._circuit_state = _CB_OPEN
                _logger.warning({
                    "message": "vllm_circuit_breaker_opened",
                    "failure_count": self._failure_count,
                    "recovery_timeout_s": self._recovery_timeout_s,
                    "exc": str(exc),
                })

    async def circuit_state(self) -> dict[str, Any]:
        """Return current circuit breaker state for health/metrics."""
        async with self._circuit_lock:
            return {
                "state": self._circuit_state,
                "open": self._is_circuit_open(),
                "failure_count": self._failure_count,
                "open_since_s": _time.monotonic() - self._circuit_open_since if self._circuit_open_since else None,
                "failure_threshold": self._failure_threshold,
                "recovery_timeout_s": self._recovery_timeout_s,
            }
