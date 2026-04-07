"""
Company Research Service - Orchestration for company research refresh pipeline.

Handles:
1. Creating refresh records and scheduling background execution
2. Acquiring raw artifacts from public sources (Glassdoor, LinkedIn)
3. Persisting raw HTML snapshots to the filesystem
4. Normalizing raw artifacts into claims and interview questions
5. Completing or failing refresh lifecycle

Follows the same service pattern as search_service.py.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Coroutine, Optional

import httpx

from research.research_store import (
    get_research_store,
    _compute_company_key,
    STALE_THRESHOLD_DAYS,
    VERY_STALE_THRESHOLD_DAYS,
)

from graph.career_event_bus import emit_career_event

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.resolve()
RESEARCH_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "research"


def _schedule_background(coro: Coroutine[object, object, object]) -> None:
    """Schedule a background coroutine without leaking it in patched tests."""
    try:
        task = asyncio.create_task(coro)
    except Exception:
        coro.close()
        raise
    if not isinstance(task, asyncio.Task):
        coro.close()


def _is_stale(stale_days: Optional[int]) -> bool:
    """Determine if research is stale based on days since last refresh."""
    return stale_days is not None and stale_days >= STALE_THRESHOLD_DAYS


async def acquire_artifacts(company_key: str) -> list[dict]:
    """
    Fetch raw HTML from public research sources for a company.

    Sources:
    - Glassdoor reviews page
    - LinkedIn company about page

    Returns list of dicts with 'source', 'url', 'html' keys.
    """
    artifacts = []
    sources = [
        {
            "name": "glassdoor",
            "url": f"https://www.glassdoor.com/Reviews/{company_key.replace('-', '-')}-Reviews.htm",
        },
        {
            "name": "linkedin",
            "url": f"https://www.linkedin.com/company/{company_key.replace('-', '')}/about/",
        },
    ]

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for source in sources:
            try:
                resp = await client.get(
                    source["url"],
                    headers={"User-Agent": "Mozilla/5.0 (compatible; ResearchBot/1.0)"},
                )
                if resp.status_code == 200:
                    artifacts.append({
                        "source": source["name"],
                        "url": str(resp.url),
                        "html": resp.text,
                    })
                else:
                    logger.warning(
                        "Source %s returned %d for %s",
                        source["name"], resp.status_code, company_key,
                    )
            except Exception as exc:
                logger.warning(
                    "Source %s fetch failed for %s: %s",
                    source["name"], company_key, exc,
                )

            # Sequential with delay (D-11): wait 2-3s between sources
            await asyncio.sleep(2.5)

    return artifacts


def persist_raw_artifacts(company_key: str, artifacts: list[dict]) -> list[str]:
    """
    Save raw HTML artifacts to the filesystem.

    Files go to outputs/research/{company_key}/YYYY-MM-DD/{source}.html

    Returns list of file paths that were persisted.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_dir = RESEARCH_OUTPUT_DIR / company_key / today
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = []
    for artifact in artifacts:
        source_name = artifact["source"]
        filename = f"{source_name}.html"
        file_path = output_dir / filename
        file_path.write_text(artifact["html"], encoding="utf-8")
        paths.append(str(file_path))
        logger.info("Persisted artifact: %s", file_path)

    return paths


def normalize_artifacts(
    company_key: str,
    company_name: str,
    artifacts: list[dict],
) -> dict:
    """
    Normalize raw artifacts into claims and interview questions.

    For the initial implementation, this extracts structured data from
    raw HTML using simple pattern matching. LLM-based extraction (D-02)
    will be added when vLLM is available.

    Returns dict with 'claims' and 'questions' lists.
    """
    claims = []
    questions = []

    for artifact in artifacts:
        source = artifact["source"]
        url = artifact["url"]
        html = artifact["html"]
        collected_at = datetime.now(timezone.utc).isoformat()

        # Simple text extraction for basic claims
        # In production, this would use LLM (D-02)
        text_content = html[:5000] if html else ""

        if not text_content:
            continue

        # Extract basic company info as claims
        if source == "glassdoor":
            claims.append({
                "claim_text": f"Research collected from Glassdoor for {company_name}",
                "source_url": url,
                "collected_at": collected_at,
                "confidence": "medium",
                "themes": ["culture", "reviews"],
                "role_applicability": ["All roles"],
            })

        elif source == "linkedin":
            claims.append({
                "claim_text": f"Research collected from LinkedIn for {company_name}",
                "source_url": url,
                "collected_at": collected_at,
                "confidence": "medium",
                "themes": ["company_overview"],
                "role_applicability": ["All roles"],
            })

    return {"claims": claims, "questions": questions}


async def execute_research_refresh(refresh_id: str, company_key: str) -> None:
    """
    Execute a full research refresh for a company.

    This runs as a background task and:
    1. Updates refresh status to 'running'
    2. Acquires artifacts from public sources
    3. Persists raw artifacts to filesystem
    4. Creates a new snapshot
    5. Normalizes into claims and questions
    6. Marks refresh as completed or failed
    """
    store = get_research_store()
    company_name = store.get_company_name(company_key) or company_key

    try:
        store.update_refresh(refresh_id, status="running")

        # Acquire artifacts
        store.update_refresh(
            refresh_id, status="running", current_source="glassdoor",
        )
        artifacts = await acquire_artifacts(company_key)

        # Persist raw artifacts
        artifact_paths = persist_raw_artifacts(company_key, artifacts)

        # Create snapshot
        snapshot = store.create_snapshot(
            company_key=company_key,
            source_count=len(artifacts),
            artifact_paths=artifact_paths,
        )

        # Normalize
        normalized = normalize_artifacts(company_key, company_name, artifacts)

        # Persist claims
        for claim_data in normalized["claims"]:
            store.add_claim(
                snapshot_id=snapshot.snapshot_id,
                company_key=company_key,
                claim_text=claim_data["claim_text"],
                source_url=claim_data["source_url"],
                collected_at=claim_data["collected_at"],
                confidence=claim_data.get("confidence", "medium"),
                themes=claim_data.get("themes"),
                sentiment_score=claim_data.get("sentiment_score"),
                role_applicability=claim_data.get("role_applicability"),
            )

        # Persist questions
        for q_data in normalized["questions"]:
            store.add_interview_question(
                snapshot_id=snapshot.snapshot_id,
                company_key=company_key,
                question_text=q_data["question_text"],
                source_url=q_data["source_url"],
                collected_at=q_data["collected_at"],
                role_applicability=q_data.get("role_applicability"),
                themes=q_data.get("themes"),
            )

        # Complete snapshot with counts
        store.complete_snapshot(
            snapshot.snapshot_id,
            claim_count=len(normalized["claims"]),
            question_count=len(normalized["questions"]),
        )

        # Complete refresh
        store.update_refresh(
            refresh_id,
            status="completed",
            sources_completed=len(artifacts),
        )

        logger.info(
            "Research refresh %s completed for %s: %d claims, %d questions",
            refresh_id, company_key,
            len(normalized["claims"]), len(normalized["questions"]),
        )

        # Emit graph event for refresh completed
        try:
            emit_career_event(
                category="research",
                action="research_refresh_completed",
                entity_id=refresh_id,
                entity_type="research_refresh",
                payload={
                    "company_key": company_key,
                    "claim_count": len(normalized["claims"]),
                    "question_count": len(normalized["questions"]),
                },
            )
        except Exception:
            logger.warning("Failed to emit graph event for research refresh_completed", exc_info=True)

    except Exception as exc:
        logger.exception("Research refresh %s failed: %s", refresh_id, exc)
        store.update_refresh(
            refresh_id, status="failed", error_message=str(exc)[:500],
        )

        # Emit graph event for refresh failed
        try:
            emit_career_event(
                category="research",
                action="research_refresh_failed",
                entity_id=refresh_id,
                entity_type="research_refresh",
                payload={"company_key": company_key, "error_message": str(exc)[:500]},
            )
        except Exception:
            logger.warning("Failed to emit graph event for research refresh_failed", exc_info=True)


def start_research_refresh(company_key: str, company_name: str) -> str:
    """
    Start a research refresh for a company.

    Creates the company record if needed, creates a refresh record,
    and schedules the async execution. Returns the refresh_id immediately.
    """
    store = get_research_store()

    # Ensure company exists
    store.ensure_company(company_key, company_name)

    # Create refresh record
    refresh = store.create_refresh(company_key, sources_total=2)

    # Emit graph event for refresh started
    try:
        emit_career_event(
            category="research",
            action="research_refresh_started",
            entity_id=refresh.refresh_id,
            entity_type="research_refresh",
            payload={"company_key": company_key},
        )
    except Exception:
        logger.warning("Failed to emit graph event for research refresh_started", exc_info=True)

    # Schedule background execution.
    _schedule_background(execute_research_refresh(refresh.refresh_id, company_key))

    return refresh.refresh_id
