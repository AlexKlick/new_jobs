"""Career graph read models — typed Pydantic response schemas for graph queries.

These models define the stable read surface exposed by the graph service and API
endpoints. They contain only derived insights (company names, role titles, counts),
never raw event payloads or user credentials.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ── Health ────────────────────────────────────────────────────────────────────


class GraphHealthResponse(BaseModel):
    """Graph worker health and event statistics."""

    status: str  # "healthy" | "initializing" | "unavailable"
    is_available: bool
    total_events: int
    processed_events: int
    pending_events: int
    last_processed_at: Optional[str] = None
    initialized_at: Optional[str] = None


# ── Company History ───────────────────────────────────────────────────────────


class CompanyHistoryEntry(BaseModel):
    """A single entry in a company's career history."""

    company_key: str
    company_name: Optional[str] = None
    event_type: str
    event_timestamp: str
    summary: str
    source: str  # which domain produced this, e.g. "search", "application"


class CompanyHistoryReadModel(BaseModel):
    """Structured company history derived from graph events."""

    company_key: str
    total_events: int
    entries: list[CompanyHistoryEntry] = Field(default_factory=list)
    related_companies: list[str] = Field(default_factory=list)
    is_degraded: bool = False


# ── Search History ────────────────────────────────────────────────────────────


class SearchHistoryEntry(BaseModel):
    """A single search run summary."""

    run_id: str
    preference_label: Optional[str] = None
    started_at: str
    completed_at: Optional[str] = None
    total_candidates: int = 0
    new_candidates: int = 0
    top_companies: list[str] = Field(default_factory=list)


class SearchHistoryReadModel(BaseModel):
    """Structured search history derived from graph events."""

    total_runs: int
    entries: list[SearchHistoryEntry] = Field(default_factory=list)
    companies_seen: list[str] = Field(default_factory=list)
    is_degraded: bool = False


# ── Degraded Response ─────────────────────────────────────────────────────────


class GraphDegradedResponse(BaseModel):
    """Returned when the graph worker is unavailable."""

    is_degraded: bool = True
    message: str = "Career memory is temporarily unavailable. Some features may be limited."
    total_events: int = 0
    suggestion: str = "Try again in a few moments."
