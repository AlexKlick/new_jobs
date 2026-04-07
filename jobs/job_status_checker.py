"""
Job Status Checker Module

Checks if job postings are still active by scraping the job URL and detecting
if the posting has been removed or closed.

Supports:
- Greenhouse job boards
- Lever job boards
- Generic URLs (HTTP status + content analysis)

Rate limiting: max 1 request per 2 seconds per domain
Timeout: 30s default
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Status enum
JobStatus = str  # 'ACTIVE' | 'CLOSED' | 'EXPIRED' | 'ERROR' | 'UNKNOWN'
JobSource = str   # 'greenhouse' | 'lever' | 'generic'


@dataclass
class JobPostingStatus:
    """Status result for a single job posting check."""
    index: int
    url: str
    status: JobStatus = 'UNKNOWN'
    last_checked: Optional[str] = None
    error: Optional[str] = None
    source: JobSource = 'generic'
    http_status_code: Optional[int] = None
    response_time_ms: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "url": self.url,
            "status": self.status,
            "lastChecked": self.last_checked,
            "error": self.error,
            "source": self.source,
            "httpStatusCode": self.http_status_code,
            "responseTimeMs": self.response_time_ms,
        }


# Rate limiting: domain -> last request timestamp
_rate_limit_store: dict[str, float] = {}
RATE_LIMIT_SECONDS = 2.0


def _get_domain(url: str) -> str:
    """Extract domain from URL for rate limiting."""
    parsed = urlparse(url)
    return parsed.netloc.lower()


def _check_rate_limit(domain: str) -> float:
    """
    Check rate limit for domain.
    Returns seconds to wait before next request.
    """
    now = time.monotonic()
    last_request = _rate_limit_store.get(domain, 0)
    elapsed = now - last_request

    if elapsed < RATE_LIMIT_SECONDS:
        wait_time = RATE_LIMIT_SECONDS - elapsed
        logger.debug(f"Rate limiting {domain}: waiting {wait_time:.2f}s")
        return wait_time

    return 0.0


def _update_rate_limit(domain: str) -> None:
    """Update the last request timestamp for a domain."""
    _rate_limit_store[domain] = time.monotonic()


async def check_rate_limit_async(domain: str) -> None:
    """Async rate limit checker - sleeps if needed."""
    wait_time = _check_rate_limit(domain)
    if wait_time > 0:
        await asyncio.sleep(wait_time)
    _update_rate_limit(domain)


def detect_job_board(url: str) -> JobSource:
    """Detect job board type from URL."""
    lower = url.lower()

    if 'greenhouse.io' in lower or 'greenhouse' in lower:
        return 'greenhouse'
    elif 'lever.co' in lower or 'work.lever' in lower:
        return 'lever'
    else:
        return 'generic'


async def _fetch_url(
    client: httpx.AsyncClient,
    url: str,
    timeout: float = 30.0
) -> tuple[Optional[int], Optional[str]]:
    """
    Fetch URL and return (http_status_code, response_text).
    Returns (None, None) on network error.
    """
    try:
        response = await client.get(url, timeout=timeout, follow_redirects=True)
        return response.status_code, response.text
    except httpx.TimeoutException:
        logger.warning(f"Timeout fetching {url}")
        return None, None
    except httpx.RequestError as e:
        logger.warning(f"Request error for {url}: {e}")
        return None, None


async def check_greenhouse(url: str, client: httpx.AsyncClient) -> tuple[JobStatus, Optional[str]]:
    """
    Check Greenhouse job posting status.
    Returns (status, error_message).
    """
    status_code, content = await _fetch_url(client, url)

    if status_code is None:
        return 'ERROR', 'Network timeout or error'

    if status_code == 404:
        return 'CLOSED', 'Job posting not found (404)'

    if status_code == 410:
        return 'EXPIRED', 'Job posting explicitly removed (410)'

    if status_code == 403:
        # Could be rate limited or access denied
        if 'captcha' in content.lower() or 'access denied' in content.lower():
            return 'ERROR', 'Access denied or captcha challenge'
        return 'ERROR', 'Access forbidden (403)'

    if status_code != 200:
        return 'ERROR', f'HTTP {status_code}'

    # Check content for closed indicators
    content_lower = content.lower()

    closed_indicators = [
        'position is no longer available',
        'this job has been closed',
        'job is no longer accepting applications',
        'this position has been filled',
        'the posting has expired',
        'application closed',
        'job closed',
    ]

    for indicator in closed_indicators:
        if indicator in content_lower:
            return 'CLOSED', f'Closed indicator found: {indicator}'

    # Check for "apply" button presence (strong active indicator)
    if 'apply' not in content_lower:
        return 'UNKNOWN', 'No apply button found in page'

    return 'ACTIVE', None


async def check_lever(url: str, client: httpx.AsyncClient) -> tuple[JobStatus, Optional[str]]:
    """
    Check Lever job posting status.
    Returns (status, error_message).
    """
    status_code, content = await _fetch_url(client, url)

    if status_code is None:
        return 'ERROR', 'Network timeout or error'

    if status_code == 404:
        return 'CLOSED', 'Job posting not found (404)'

    if status_code == 410:
        return 'EXPIRED', 'Job posting explicitly removed (410)'

    if status_code == 403:
        return 'ERROR', 'Access forbidden (403)'

    if status_code != 200:
        return 'ERROR', f'HTTP {status_code}'

    content_lower = content.lower()

    closed_indicators = [
        'no longer accepting applications',
        'this position has been filled',
        'job is no longer available',
        'position closed',
        'applications closed',
    ]

    for indicator in closed_indicators:
        if indicator in content_lower:
            return 'CLOSED', f'Closed indicator found: {indicator}'

    # Check for working apply link
    if 'apply' not in content_lower and 'submit' not in content_lower:
        return 'UNKNOWN', 'No apply/submit button found in page'

    return 'ACTIVE', None


async def check_generic(url: str, client: httpx.AsyncClient) -> tuple[JobStatus, Optional[str]]:
    """
    Check generic job posting URL.
    Returns (status, error_message).
    """
    status_code, content = await _fetch_url(client, url)

    if status_code is None:
        return 'ERROR', 'Network timeout or error'

    if status_code == 404:
        return 'CLOSED', 'Page not found (404)'

    if status_code == 410:
        return 'EXPIRED', 'Page explicitly removed (410)'

    if status_code == 403:
        return 'ERROR', 'Access forbidden (403)'

    if status_code == 401:
        return 'ERROR', 'Authentication required (401)'

    if status_code >= 500:
        return 'ERROR', f'Server error ({status_code})'

    if status_code != 200:
        return 'ERROR', f'HTTP {status_code}'

    content_lower = content.lower()

    # Generic closed indicators
    closed_indicators = [
        'position is no longer available',
        'job is no longer available',
        'this position has been filled',
        'no longer accepting applications',
        'applications closed',
        'position closed',
        'job expired',
    ]

    for indicator in closed_indicators:
        if indicator in content_lower:
            return 'CLOSED', f'Closed indicator found: {indicator}'

    return 'ACTIVE', None


async def check_job_status(index: int, url: str, timeout: float = 30.0) -> JobPostingStatus:
    """
    Check the status of a single job posting.

    Args:
        index: Job index from the manifest
        url: Job application URL
        timeout: Request timeout in seconds

    Returns:
        JobPostingStatus with status, timestamps, and error info
    """
    import datetime

    start_time = time.monotonic()
    result = JobPostingStatus(index=index, url=url)
    result.last_checked = datetime.datetime.utcnow().isoformat() + 'Z'

    # Detect job board type
    source = detect_job_board(url)
    result.source = source

    logger.info(f"Checking job #{index} ({source}): {url}")

    # Apply rate limiting
    domain = _get_domain(url)
    await check_rate_limit_async(domain)

    # Create client with realistic headers
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }

    async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
        if source == 'greenhouse':
            status, error = await check_greenhouse(url, client)
        elif source == 'lever':
            status, error = await check_lever(url, client)
        else:
            status, error = await check_generic(url, client)

        result.status = status
        result.error = error

    end_time = time.monotonic()
    result.response_time_ms = int((end_time - start_time) * 1000)

    logger.info(f"Job #{index} status: {status} ({result.response_time_ms}ms)")

    return result


async def check_all_jobs(
    jobs: list[tuple[int, str]],
    max_concurrent: int = 5,
    timeout: float = 30.0
) -> list[JobPostingStatus]:
    """
    Check status for multiple jobs with controlled concurrency.

    Args:
        jobs: List of (index, url) tuples
        max_concurrent: Maximum concurrent requests
        timeout: Request timeout per job

    Returns:
        List of JobPostingStatus results
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def check_with_semaphore(index: int, url: str) -> JobPostingStatus:
        async with semaphore:
            return await check_job_status(index, url, timeout)

    tasks = [check_with_semaphore(index, url) for index, url in jobs]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Convert exceptions to ERROR statuses
    processed_results: list[JobPostingStatus] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            index, url = jobs[i]
            import datetime
            processed_results.append(JobPostingStatus(
                index=index,
                url=url,
                status='ERROR',
                error=str(result),
                last_checked=datetime.datetime.utcnow().isoformat() + 'Z',
            ))
            logger.error(f"Job #{index} raised exception: {result}")
        else:
            processed_results.append(result)

    return processed_results


# Synchronous wrappers for non-async contexts
def check_job_status_sync(index: int, url: str, timeout: float = 30.0) -> JobPostingStatus:
    """Synchronous wrapper for check_job_status."""
    return asyncio.run(check_job_status(index, url, timeout))


def check_all_jobs_sync(
    jobs: list[tuple[int, str]],
    max_concurrent: int = 5,
    timeout: float = 30.0
) -> list[JobPostingStatus]:
    """Synchronous wrapper for check_all_jobs."""
    return asyncio.run(check_all_jobs(jobs, max_concurrent, timeout))
