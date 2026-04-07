"""
Circuit Breaker for Agent Escalation Loops

Tracks escalation attempts within a sliding window. After 3 escalations in 5 minutes,
opens the circuit and stops further escalation attempts.

Usage:
    cb = AgentCircuitBreaker(threshold=3, window_s=300)
    await cb.record_escalation(session_id)

    if await cb.is_open():
        raise CircuitBreakerOpenError("Too many escalations")
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


@dataclass
class EscalationEvent:
    """Record of a single escalation attempt."""
    timestamp: float
    session_id: str


class CircuitBreakerOpenError(Exception):
    """Raised when the circuit breaker is open."""
    pass


class AgentCircuitBreaker:
    """Circuit breaker for agent escalation loops.

    Tracks escalation attempts within a sliding window. After threshold
    escalations in the window, the circuit opens.
    """

    def __init__(
        self,
        threshold: int = 3,
        window_s: int = 300,  # 5 minutes
    ):
        """Initialize circuit breaker.

        Args:
            threshold: Number of escalations before opening circuit (default: 3)
            window_s: Sliding window size in seconds (default: 300 = 5 minutes)
        """
        self._threshold = threshold
        self._window_s = window_s
        self._events: list[EscalationEvent] = []
        self._lock = asyncio.Lock()

    async def record_escalation(self, session_id: str) -> None:
        """Record an escalation attempt.

        Args:
            session_id: Session ID where escalation occurred
        """
        async with self._lock:
            now = time.monotonic()
            # Remove events outside the window
            self._events = [
                e for e in self._events
                if now - e.timestamp < self._window_s
            ]
            self._events.append(EscalationEvent(timestamp=now, session_id=session_id))
            _logger.info(f"Recorded escalation for session {session_id}, total in window: {len(self._events)}")

    async def is_open(self) -> bool:
        """Check if circuit is open (escalation limit reached).

        Returns:
            True if circuit is open, False otherwise
        """
        async with self._lock:
            now = time.monotonic()
            # Remove old events
            self._events = [
                e for e in self._events
                if now - e.timestamp < self._window_s
            ]
            is_open = len(self._events) >= self._threshold
            if is_open:
                _logger.warning(f"Circuit breaker open: {len(self._events)} escalations in window")
            return is_open

    async def get_status(self) -> dict[str, Any]:
        """Return circuit breaker status for health/metrics.

        Returns:
            Dict with circuit state information
        """
        async with self._lock:
            now = time.monotonic()
            # Remove old events
            active = [
                e for e in self._events
                if now - e.timestamp < self._window_s
            ]

            resets_in = 0
            if active:
                oldest = min(e.timestamp for e in active)
                resets_in = max(0, self._window_s - (now - oldest))

            return {
                "open": len(active) >= self._threshold,
                "escalation_count": len(active),
                "threshold": self._threshold,
                "window_s": self._window_s,
                "resets_in_s": resets_in,
            }

    async def reset(self) -> None:
        """Reset the circuit breaker (close it)."""
        async with self._lock:
            self._events.clear()
            _logger.info("Circuit breaker reset")

    async def wait_if_open(self) -> float:
        """Wait until circuit closes (if open).

        Returns:
            Time waited in seconds

        Raises:
            CircuitBreakerOpenError: If circuit is open
        """
        if not await self.is_open():
            return 0

        status = await self.get_status()
        if status["resets_in_s"] > 0:
            _logger.info(f"Circuit breaker waiting {status['resets_in_s']}s for reset")
            await asyncio.sleep(status["resets_in_s"])

        return status.get("resets_in_s", 0)
