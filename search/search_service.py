"""Search service - ATS plus discovery-driven job search execution pipeline.

Handles:
1. Greenhouse and Lever board scraping
2. Keyword and location filtering
3. Background execution via asyncio.create_task
4. Normalized candidate extraction
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Coroutine, Optional
from urllib.parse import urljoin, urlsplit

import httpx

from search.search_store import SearchStore, get_search_store, SearchPreferenceModel
from graph.career_event_bus import emit_career_event

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def _schedule_background(coro: Coroutine[Any, Any, Any]) -> None:
    """Schedule a background coroutine without leaking it in patched tests."""
    try:
        task = asyncio.create_task(coro)
    except Exception:
        coro.close()
        raise
    if not isinstance(task, asyncio.Task):
        coro.close()


async def _call_store(
    store: SearchStore,
    async_name: str,
    sync_name: str,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Use async store methods when the implementation provides them."""
    async_descriptor = getattr(type(store), async_name, None)
    if callable(async_descriptor):
        result = getattr(store, async_name)(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result
    return getattr(store, sync_name)(*args, **kwargs)


def _emit_search_run_started(run_id: str, preference: SearchPreferenceModel) -> None:
    """Emit the standard search-run-started graph event."""
    try:
        emit_career_event(
            category="search",
            action="search_run_started",
            entity_id=run_id,
            entity_type="search_run",
            payload={
                "preference_id": preference.preference_id,
                "keywords": preference.keywords,
                "locations": preference.locations,
            },
        )
    except Exception:
        logger.warning("Failed to emit graph event for search run_started", exc_info=True)


# ── URL Builders ────────────────────────────────────────────────────────────────


def greenhouse_search_url(company: str) -> str:
    """Build a Greenhouse jobs board URL for a company."""
    return f"https://boards.greenhouse.io/{company}/jobs?content=true"


def lever_jobs_url(company: str) -> str:
    """Build a Lever jobs API URL for a company."""
    return f"https://api.lever.co/v0/postings/{company}?mode=json"


def build_greenhouse_query(keywords: list[str], locations: list[str]) -> str:
    """Build a Greenhouse search URL from keywords and locations."""
    base = "https://boards.greenhouse.io"
    query_parts = []
    if keywords:
        query_parts.append("+".join(keywords))
    if locations:
        query_parts.append("+".join(locations))
    return f"{base}?q={'+'.join(query_parts)}" if query_parts else base


def build_lever_query(keywords: list[str], locations: list[str]) -> str:
    """Build a Lever search URL from keywords and locations."""
    base = "https://api.lever.co/v0/postings"
    query_parts = []
    if keywords:
        query_parts.append("+".join(keywords))
    if locations:
        query_parts.append("+".join(locations))
    return f"{base}?q={'+'.join(query_parts)}" if query_parts else base


def _extract_company_from_url(url: str, source: str) -> str:
    """Extract company slug from ATS URL."""
    if not url:
        return source
    try:
        parsed = urlsplit(url)
        path = parsed.path.strip("/")
        if "greenhouse.io" in parsed.netloc:
            parts = path.split("/")
            if parts:
                return parts[0]
        elif "lever.co" in parsed.netloc:
            # jobs.lever.co/{company}/... or api.lever.co/v0/postings/{company}/...
            parts = path.split("/")
            for i, p in enumerate(parts):
                if p == "postings" and i + 1 < len(parts):
                    return parts[i + 1]
            # jobs.lever.co/{company}/{job_id}
            if len(parts) >= 2:
                return parts[0]
    except Exception:
        pass
    return source


# ── Normalization ──────────────────────────────────────────────────────────────


def parse_salary_range(text: str | None) -> int | None:
    """Extract minimum salary from a range string like '$180k-$220k'."""
    if not text:
        return None
    match = re.search(r"\$(\d+)\s*k", text)
    if match:
        return int(match.group(1)) * 1000
    return None


def normalize_greenhouse_job(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize a Greenhouse job posting into a standard candidate dict."""
    if not raw:
        return None
    title = raw.get("title", "")
    if not title:
        return None

    url = raw.get("absolute_url", "")
    company = _extract_company_from_url(url, "greenhouse")

    location_parts: list[str] = []
    for meta in raw.get("metadata", []):
        if meta.get("name") == "Location":
            vals = meta.get("value", [])
            if isinstance(vals, list):
                location_parts.extend(vals)
            elif isinstance(vals, str):
                location_parts.append(vals)
        elif meta.get("name") == "Salary Range":
            pass  # handled below
        elif meta.get("name") == "Workplace Type":
            pass  # handled below

    location = ", ".join(location_parts) if location_parts else None

    # Extract salary
    salary = None
    for meta in raw.get("metadata", []):
        if meta.get("name") == "Salary Range":
            vals = meta.get("value", [])
            if isinstance(vals, list) and vals:
                salary = vals[0]
            elif isinstance(vals, str):
                salary = vals

    # Extract remote
    remote = None
    for meta in raw.get("metadata", []):
        if meta.get("name") == "Workplace Type":
            vals = meta.get("value", [])
            if isinstance(vals, list) and vals:
                remote = vals[0].lower()
            elif isinstance(vals, str):
                remote = vals.lower()

    # Extract experience level from title
    experience_level = None
    title_lower = title.lower()
    if "senior" in title_lower or "staff" in title_lower or "principal" in title_lower:
        experience_level = "senior"
    elif "junior" in title_lower or "entry" in title_lower or "intern" in title_lower:
        experience_level = "junior"
    elif "mid" in title_lower:
        experience_level = "mid"

    posted_date = raw.get("updated_at", "")
    if posted_date:
        posted_date = posted_date[:10]  # ISO date portion

    result: dict[str, Any] = {
        "company": company,
        "role": title,
        "location": location,
        "salary": salary,
        "remote": remote,
        "source": "greenhouse",
        "source_url": url,
        "apply_url": url,
        "posted_date": posted_date,
        "experience_level": experience_level,
    }
    return result


def normalize_lever_job(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize a Lever job posting into a standard candidate dict."""
    if not raw:
        return None

    title = raw.get("text", "")
    if not title:
        return None

    company = raw.get("company", {}).get("name", "") if isinstance(raw.get("company"), dict) else raw.get("company", "")
    if not company:
        # Fallback: extract from URL
        apply_url = ""
        urls = raw.get("urls", {})
        if isinstance(urls, dict):
            apply_url = urls.get("apply", "")
        company = _extract_company_from_url(apply_url, "lever")

    location = None
    categories = raw.get("categories", {})
    if isinstance(categories, dict):
        loc = categories.get("location", "")
        if isinstance(loc, list):
            location = ", ".join(loc)
        elif isinstance(loc, str):
            location = loc

    urls = raw.get("urls", {})
    apply_url = ""
    if isinstance(urls, dict):
        apply_url = urls.get("apply", "")

    posted_date = raw.get("updatedAt", "")
    if posted_date:
        posted_date = posted_date[:10]

    result: dict[str, Any] = {
        "company": company,
        "role": title,
        "location": location,
        "salary": None,
        "remote": None,
        "source": "lever",
        "source_url": apply_url,
        "apply_url": apply_url,
        "posted_date": posted_date,
    }
    return result


# ── JSON-LD extraction ─────────────────────────────────────────────────────────


def _extract_jsonld_jobs(
    html: str,
    *,
    source: str,
    discovery_url: str,
    source_url: str,
) -> list[dict[str, Any]]:
    """Extract JobPosting entries from JSON-LD script tags in HTML."""
    jobs = []
    pattern = re.compile(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.DOTALL,
    )
    for match in pattern.finditer(html):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue

        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            job: dict[str, Any] = {
                "role": data.get("title", ""),
                "company": data.get("hiringOrganization", {}).get("name", "")
                if isinstance(data.get("hiringOrganization"), dict)
                else "",
                "source": source,
                "source_url": data.get("url") or source_url,
                "apply_url": data.get("url") or source_url,
                "discovery_url": discovery_url,
                "source_confidence": "low" if source == "generic_web" else "medium",
                "location": data.get("jobLocation", {})
                .get("address", {})
                .get("addressLocality", "")
                if isinstance(data.get("jobLocation"), dict)
                else "",
                "posted_date": data.get("datePosted", ""),
            }
            if job["role"]:
                jobs.append(job)

    return jobs


# ── Preference matching ────────────────────────────────────────────────────────


def _matches_preference(candidate: dict[str, Any], pref: SearchPreferenceModel) -> bool:
    """Check if a candidate matches a search preference's filters."""
    # Keyword match
    cand_text = f"{candidate.get('role', '')} {candidate.get('company', '')}".lower()
    if pref.keywords:
        if not any(kw.lower() in cand_text for kw in pref.keywords):
            return False

    # Location match
    if pref.locations:
        cand_loc = (candidate.get("location") or "").lower()
        matched_loc = False
        for loc in pref.locations:
            if loc.lower() in cand_loc:
                matched_loc = True
                break
        if not matched_loc:
            return False

    # Remote policy
    if pref.remote_policy:
        cand_remote = (candidate.get("remote") or "").lower()
        if pref.remote_policy == "remote" and cand_remote != "remote":
            return False

    # Salary minimum
    if pref.salary_min:
        cand_salary_text = candidate.get("salary")
        if not cand_salary_text:
            return False
        cand_salary = parse_salary_range(str(cand_salary_text))
        if cand_salary is None or cand_salary < pref.salary_min:
            return False

    # Experience level
    if pref.experience_level:
        cand_exp = (candidate.get("experience_level") or "").lower()
        if cand_exp != pref.experience_level.lower():
            return False

    return True


# ── Search execution ──────────────────────────────────────────────────────────


async def execute_search_run(run_id: str, preference: SearchPreferenceModel) -> None:
    """Execute a search run: fetch from sources, normalize, and store results."""
    store = get_search_store()

    try:
        await _call_store(store, "update_run_status_async", "update_run_status", run_id, "running")

        all_candidates: list[dict[str, Any]] = []
        warnings: list[str] = []

        for source in preference.sources:
            try:
                if source == "greenhouse":
                    candidates = await _fetch_greenhouse(preference)
                elif source == "lever":
                    candidates = await _fetch_lever(preference)
                else:
                    warnings.append(f"Unknown source: {source}")
                    continue
                all_candidates.extend(candidates)
            except Exception as exc:
                warnings.append(f"{source} fetch failed: {exc}")

        # Filter by preference
        matched = [c for c in all_candidates if _matches_preference(c, preference)]

        # Add to store
        for cand in matched:
            await _call_store(
                store,
                "add_candidate_async",
                "add_candidate",
                run_id=run_id,
                source=cand.get("source", ""),
                source_url=cand.get("source_url", ""),
                company=cand.get("company", ""),
                role=cand.get("role", ""),
                location=cand.get("location"),
                salary=cand.get("salary"),
                remote=cand.get("remote"),
                posted_date=cand.get("posted_date"),
                apply_url=cand.get("apply_url"),
                discovery_url=cand.get("discovery_url"),
                extraction_method=cand.get("extraction_method", "ats_api"),
                source_confidence=cand.get("source_confidence", "high"),
                search_rank=cand.get("search_rank", 0),
            )

        # Compute counts - handle mock stores that return nothing
        counts = await _call_store(store, "compute_run_counts_async", "compute_run_counts", run_id)
        total, new, dupes = 0, 0, 0
        if counts and len(counts) == 3:
            total, new, dupes = counts
            await _call_store(
                store,
                "update_run_counts_async",
                "update_run_counts",
                run_id,
                total,
                new,
                dupes,
            )
        await _call_store(
            store,
            "update_run_status_async",
            "update_run_status",
            run_id,
            "completed",
            warnings=warnings if warnings else None,
        )

        # Emit graph event for run completed
        try:
            emit_career_event(
                category="search",
                action="search_run_completed",
                entity_id=run_id,
                entity_type="search_run",
                payload={
                    "candidate_count": total,
                    "new_candidates": new,
                    "source_counts": {},
                },
            )
        except Exception:
            logger.warning("Failed to emit graph event for search run_completed", exc_info=True)

    except Exception as exc:
        logger.exception("Search run %s failed: %s", run_id, exc)
        await _call_store(
            store,
            "update_run_status_async",
            "update_run_status",
            run_id,
            "failed",
            error_message=str(exc)[:500],
        )

        # Emit graph event for run failed
        try:
            emit_career_event(
                category="search",
                action="search_run_failed",
                entity_id=run_id,
                entity_type="search_run",
                payload={"error_message": str(exc)[:500]},
            )
        except Exception:
            logger.warning("Failed to emit graph event for search run_failed", exc_info=True)


async def _fetch_greenhouse(preference: SearchPreferenceModel) -> list[dict[str, Any]]:
    """Fetch candidates from Greenhouse boards."""
    candidates = []
    companies = preference.companies or []
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for company in companies:
            try:
                url = greenhouse_search_url(company)
                resp = await client.get(url)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                for job in data.get("jobs", []):
                    normalized = normalize_greenhouse_job(job)
                    if normalized:
                        candidates.append(normalized)
            except Exception as exc:
                logger.warning("Greenhouse fetch failed for %s: %s", company, exc)
    return candidates


async def _fetch_lever(preference: SearchPreferenceModel) -> list[dict[str, Any]]:
    """Fetch candidates from Lever boards."""
    candidates = []
    companies = preference.companies or []
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for company in companies:
            try:
                url = lever_jobs_url(company)
                resp = await client.get(url)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if isinstance(data, list):
                    for job in data:
                        normalized = normalize_lever_job(job)
                        if normalized:
                            candidates.append(normalized)
            except Exception as exc:
                logger.warning("Lever fetch failed for %s: %s", company, exc)
    return candidates


def start_search_run(preference: SearchPreferenceModel) -> str:
    """Create a search run and schedule background execution. Returns run_id."""
    store = get_search_store()
    run = store.create_run(
        preference_id=preference.preference_id,
        preference_label=preference.label,
    )

    # Update preference last_run_at
    store.update_preference_last_run(preference.preference_id)
    _emit_search_run_started(run.run_id, preference)

    # Schedule background execution.
    _schedule_background(execute_search_run(run.run_id, preference))

    return run.run_id


async def start_search_run_async(preference: SearchPreferenceModel) -> str:
    """Create a search run asynchronously and schedule background execution."""
    store = get_search_store()
    run = await _call_store(
        store,
        "create_run_async",
        "create_run",
        preference_id=preference.preference_id,
        preference_label=preference.label,
    )
    await _call_store(
        store,
        "update_preference_last_run_async",
        "update_preference_last_run",
        preference.preference_id,
    )
    _emit_search_run_started(run.run_id, preference)
    _schedule_background(execute_search_run(run.run_id, preference))
    return run.run_id
