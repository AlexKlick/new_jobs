"""Canonical-ingest bridge for search candidate promotion."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from graph.career_event_bus import emit_career_event

logger = logging.getLogger(__name__)


class CanonicalIngestRequestError(Exception):
    """Raised when a candidate cannot be ingested because the request is invalid."""


class CanonicalIngestConfigurationError(Exception):
    """Raised when the configured ingest provider is unavailable."""


@dataclass
class CanonicalIngestResult:
    canonical_job_index: int
    already_exists: bool
    ingested_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_job_index": self.canonical_job_index,
            "already_exists": self.already_exists,
            "ingested_url": self.ingested_url,
        }


def _ensure_agent_sdk_imports(settings: Any) -> tuple[Any, Any, Any, Any]:
    root = getattr(settings, "agent_sdk_root", None)
    if not root:
        raise CanonicalIngestConfigurationError("AGENT_SDK_ROOT is not configured")

    root_path = Path(root).expanduser().resolve()
    if not root_path.exists():
        raise CanonicalIngestConfigurationError(f"AGENT_SDK_ROOT does not exist: {root_path}")
    if str(root_path) not in sys.path:
        sys.path.insert(0, str(root_path))

    try:
        from agents_sdk.client import Provider
        from agents_sdk.resume_agent.scrapers import JobScraperFactory, ingest_job_url
        from agents_sdk.resume_agent.unified_workspace import build_canonical_jobs, consolidate_workspace
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise CanonicalIngestConfigurationError(
            f"Agents SDK imports unavailable: {exc}"
        ) from exc

    return Provider, JobScraperFactory, ingest_job_url, (build_canonical_jobs, consolidate_workspace)


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.lower().split())


def _normalize_apply_url(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    if not value:
        return ""
    try:
        from urllib.parse import urlsplit, urlunsplit

        split = urlsplit(value)
    except Exception:
        return ""
    if split.scheme.lower() not in {"http", "https"} or not split.netloc:
        return ""
    path = split.path.rstrip("/") or "/"
    query = "&".join(sorted(part for part in split.query.split("&") if part))
    return urlunsplit((split.scheme.lower(), split.netloc.lower(), path, query, ""))


def _find_existing_manifest_match(
    candidate: Any,
    jobs: list[dict[str, Any]],
) -> CanonicalIngestResult | None:
    target_url = _normalize_apply_url(getattr(candidate, "apply_url", None) or getattr(candidate, "source_url", None))
    target_company = _normalize_text(getattr(candidate, "company", None))
    target_role = _normalize_text(getattr(candidate, "role", None))

    for job_record in jobs:
        job = job_record.get("job") or {}
        existing_url = _normalize_apply_url(job.get("apply_url") or job.get("apply"))
        existing_company = _normalize_text(job.get("company"))
        existing_role = _normalize_text(job.get("role"))
        if target_url and existing_url == target_url:
            return CanonicalIngestResult(
                canonical_job_index=int(job_record.get("canonical_index") or job.get("index") or 0),
                already_exists=True,
                ingested_url=job.get("apply_url") or job.get("apply"),
            )
        if not target_url and target_company and target_role and existing_company == target_company and existing_role == target_role:
            return CanonicalIngestResult(
                canonical_job_index=int(job_record.get("canonical_index") or job.get("index") or 0),
                already_exists=True,
                ingested_url=job.get("apply_url") or job.get("apply"),
            )
    return None


class AgentsSdkCanonicalIngestBridge:
    """Bridge to the repo's existing Agents SDK ingestion and workspace consolidation flow."""

    async def ingest(self, *, candidate: Any, target_url: str, settings: Any) -> CanonicalIngestResult:
        Provider, JobScraperFactory, ingest_job_url, unified_workspace = _ensure_agent_sdk_imports(settings)
        build_canonical_jobs, consolidate_workspace = unified_workspace

        workspace_root = Path(settings.canonical_workspace_root).expanduser().resolve()
        jobs_path = workspace_root / "jobs.md"

        factory = JobScraperFactory()
        job = await ingest_job_url(
            url=target_url,
            jobs_path=jobs_path,
            factory=factory,
            provider=Provider.ANTHROPIC_PRO,
            fallback_provider=None,
            max_turns=6,
            cwd=workspace_root,
        )
        consolidate_workspace(
            workspace_root,
            extra_workspaces=list(getattr(settings, "legacy_workspaces", ()) or ()),
            write_jobs=True,
            write_report=True,
        )

        normalized_target_url = _normalize_apply_url(job.apply_url or target_url)
        target_company = _normalize_text(job.company)
        target_role = _normalize_text(job.role)
        for record in build_canonical_jobs(
            workspace_root,
            extra_workspaces=list(getattr(settings, "legacy_workspaces", ()) or ()),
        ):
            record_url = _normalize_apply_url(record.job.apply_url or record.job.apply)
            if normalized_target_url and record_url == normalized_target_url:
                return CanonicalIngestResult(
                    canonical_job_index=record.canonical_index,
                    already_exists=False,
                    ingested_url=record.job.apply_url or record.job.apply,
                )
            if not normalized_target_url and _normalize_text(record.job.company) == target_company and _normalize_text(record.job.role) == target_role:
                return CanonicalIngestResult(
                    canonical_job_index=record.canonical_index,
                    already_exists=False,
                    ingested_url=record.job.apply_url or record.job.apply,
                )

        raise CanonicalIngestConfigurationError(
            f"Ingested job could not be resolved in canonical workspace for URL: {target_url}"
        )


async def ingest_candidate_into_canonical_inventory(
    candidate: Any,
    *,
    settings: Any,
    load_jobs_manifest: Callable[[], list[dict]],
) -> CanonicalIngestResult:
    target_url = getattr(candidate, "apply_url", None) or getattr(candidate, "source_url", None)
    if not target_url:
        raise CanonicalIngestRequestError("Candidate is missing an apply URL")

    existing = _find_existing_manifest_match(candidate, load_jobs_manifest())
    if existing is not None:
        result = existing
    elif getattr(settings, "canonical_ingest_provider", "") != "agents_sdk":
        raise CanonicalIngestConfigurationError(
            f"Unsupported canonical ingest provider: {getattr(settings, 'canonical_ingest_provider', None)}"
        )
    else:
        bridge = AgentsSdkCanonicalIngestBridge()
        result = await bridge.ingest(candidate=candidate, target_url=target_url, settings=settings)

    # Emit graph event for application ingested
    try:
        emit_career_event(
            category="application",
            action="application_ingested",
            entity_id=getattr(candidate, "candidate_id", ""),
            entity_type="job_candidate",
            payload={
                "canonical_job_index": result.canonical_job_index,
                "company": getattr(candidate, "company", ""),
                "role": getattr(candidate, "role", ""),
                "already_exists": result.already_exists,
            },
        )
    except Exception:
        logger.warning("Failed to emit graph event for application ingested", exc_info=True)

    return result
