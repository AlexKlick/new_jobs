"""
Job Status Checker API Server

FastAPI server for checking job posting status.
Provides endpoints for single and batch status checks.
Provides endpoints for updating markdown documents.

Run with: uvicorn api_server:app --reload --port 8080
"""

import asyncio
import json
import logging
import os
import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field

import job_status_checker as jsc
import pdf_generator as pdf_gen
from canonical_ingest import (
    CanonicalIngestConfigurationError,
    CanonicalIngestRequestError,
    ingest_candidate_into_canonical_inventory,
)
from db import close_pool, configure_runtime_pool, create_pool, ensure_schema
from db.state_store import (
    load_job_posting_statuses,
    save_job_posting_statuses,
    state_store_enabled,
)
from graph.career_graph_service import get_career_graph_service
from graph.career_graph_worker import get_career_graph_worker
from runtime_settings import get_runtime_settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Paths
PROJECT_ROOT = Path(__file__).parent.resolve()
MANIFEST_PATH = PROJECT_ROOT / "jobs_manifest.json"
STATUS_FILE = PROJECT_ROOT / "job_posting_status.json"
APPLICATIONS_DIR = PROJECT_ROOT / "applications" / "all_jobs"

# Document path helpers
MAX_CONTENT_SIZE = 500_000  # 500 KB


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def get_bundle_dir(index: int) -> Optional[Path]:
    """Find the bundle directory for a job index."""
    if not APPLICATIONS_DIR.exists():
        return None
    # Match directory names like "05_remesh__..." for index 5
    prefix = f"{index:02d}_"
    for entry in APPLICATIONS_DIR.iterdir():
        if entry.is_dir() and entry.name.startswith(prefix):
            return entry
    return None

def get_document_path(index: int, doc_type: str) -> Optional[Path]:
    """Get the path to a document file for a job."""
    bundle_dir = get_bundle_dir(index)
    if not bundle_dir:
        return None
    filename = "resume.md" if doc_type == "resume" else "cover_letter.md"
    path = bundle_dir / filename
    return path if path.exists() else None


def get_pdf_path(index: int, doc_type: str) -> Optional[Path]:
    """Get the path to a PDF file for a job."""
    bundle_dir = get_bundle_dir(index)
    if not bundle_dir:
        return None
    filename = "resume.pdf" if doc_type == "resume" else "cover_letter.pdf"
    path = bundle_dir / filename
    return path if path.exists() else None


def _postgres_runtime_requested() -> bool:
    """Return True when PostgreSQL-backed runtime state should be attempted."""
    if os.environ.get("DENJOBS_ENABLE_POSTGRES") == "1":
        return True
    dsn = os.environ.get("DATABASE_URL", "").strip().lower()
    return dsn.startswith("postgres://") or dsn.startswith("postgresql://")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan for optional PostgreSQL and graph worker startup."""
    pg_pool = None
    app.state.pg_pool = None
    configure_runtime_pool(None)

    if _postgres_runtime_requested():
        try:
            pg_pool = await create_pool()
            await ensure_schema(pg_pool)
            app.state.pg_pool = pg_pool
            configure_runtime_pool(pg_pool)
            logger.info("PostgreSQL runtime state enabled")
        except Exception as exc:
            logger.warning(
                "PostgreSQL initialization failed; continuing with file-backed state: %s",
                exc,
            )
            if pg_pool is not None:
                await close_pool(pg_pool)
                pg_pool = None

    worker = get_career_graph_worker()
    try:
        await worker.initialize()
        logger.info("Graph worker initialized successfully")
    except Exception as exc:
        logger.warning("Graph worker initialization failed: %s", exc)

    try:
        yield
    finally:
        configure_runtime_pool(None)
        if pg_pool is not None:
            await close_pool(pg_pool)

# FastAPI app
app = FastAPI(
    title="Job Status Checker API",
    description="API for checking if job postings are still active",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware - allow frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to frontend origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Models ---

class StatusCheckResponse(BaseModel):
    """Response for a single job status check."""
    index: int
    url: str
    status: str
    lastChecked: Optional[str] = None
    error: Optional[str] = None
    source: str
    httpStatusCode: Optional[int] = None
    responseTimeMs: Optional[int] = None


class StatusResponse(BaseModel):
    """Response for getting cached status."""
    index: int
    url: str
    status: str
    lastChecked: Optional[str] = None
    error: Optional[str] = None
    source: str
    httpStatusCode: Optional[int] = None
    responseTimeMs: Optional[int] = None
    cached: bool = True


class BatchCheckResponse(BaseModel):
    """Response for batch status check."""
    total: int
    completed: int
    results: list[StatusCheckResponse]


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    jobs_loaded: int


class MarkdownUpdateRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=MAX_CONTENT_SIZE)


class MarkdownUpdateResponse(BaseModel):
    index: int
    document: str
    saved: bool
    backup_path: Optional[str] = None
    error: Optional[str] = None


class RegenerateResponse(BaseModel):
    index: int
    document: str
    success: bool
    pdf_path: Optional[str] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None


# --- Persistence ---

def load_jobs_manifest() -> list[dict]:
    """Load jobs from manifest file."""
    if not MANIFEST_PATH.exists():
        return []
    with open(MANIFEST_PATH, 'r', encoding="utf-8") as f:
        data = json.load(f)
    return data.get('jobs', [])


def _load_status_store_from_file() -> dict[int, dict]:
    """Load cached status from the legacy JSON file."""
    if not STATUS_FILE.exists():
        return {}
    try:
        with open(STATUS_FILE, 'r', encoding="utf-8") as f:
            data = json.load(f)
        return {entry['index']: entry for entry in data.get('statuses', [])}
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Could not load status store: {e}")
        return {}


def _save_status_store_to_file(statuses: list[dict]) -> None:
    """Save status to the legacy JSON file atomically."""
    data = {
        'updated_at': _utc_now(),
        'statuses': statuses,
    }
    tmp_path = STATUS_FILE.with_suffix('.tmp')
    with open(tmp_path, 'w', encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    tmp_path.rename(STATUS_FILE)
    logger.info(f"Saved {len(statuses)} statuses to {STATUS_FILE}")


async def load_status_store() -> dict[int, dict]:
    """Load cached job status, merging PostgreSQL rows over legacy file data."""
    store = _load_status_store_from_file()
    if not state_store_enabled():
        return store

    try:
        pg_store = await load_job_posting_statuses()
    except Exception as exc:
        logger.warning("Could not load PostgreSQL status store: %s", exc)
        return store

    store.update(pg_store)
    return store


async def save_status_store(statuses: list[dict]) -> None:
    """Persist cached job status to PostgreSQL when available, else the file store."""
    if state_store_enabled():
        try:
            await save_job_posting_statuses(statuses)
            logger.info("Saved %s statuses to PostgreSQL", len(statuses))
            return
        except Exception as exc:
            logger.warning("Could not save PostgreSQL status store: %s", exc)

    _save_status_store_to_file(statuses)


def get_job_url(index: int) -> Optional[str]:
    """Get job URL from manifest by index."""
    jobs = load_jobs_manifest()
    for job_entry in jobs:
        if job_entry.get('canonical_index') == index or job_entry.get('job', {}).get('index') == index:
            return job_entry.get('job', {}).get('apply_url') or job_entry.get('job', {}).get('apply')
    return None


def get_all_jobs() -> list[tuple[int, str]]:
    """Get all (index, url) pairs from manifest."""
    jobs = load_jobs_manifest()
    result = []
    for job_entry in jobs:
        canonical_index = job_entry.get('canonical_index')
        job_data = job_entry.get('job', {})
        url = job_data.get('apply_url') or job_data.get('apply')
        if canonical_index and url:
            result.append((canonical_index, url))
    return result


# --- API Endpoints ---

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    jobs = load_jobs_manifest()
    return HealthResponse(
        status="ok",
        timestamp=_utc_now(),
        jobs_loaded=len(jobs),
    )


@app.get("/api/jobs/{index}/status", response_model=StatusResponse)
async def get_job_status(index: int):
    """
    Get cached status for a single job.
    Does not trigger a new check.
    """
    store = await load_status_store()

    if index in store:
        entry = store[index]
        return StatusResponse(
            index=entry['index'],
            url=entry['url'],
            status=entry['status'],
            lastChecked=entry.get('lastChecked'),
            error=entry.get('error'),
            source=entry.get('source', 'generic'),
            httpStatusCode=entry.get('httpStatusCode'),
            responseTimeMs=entry.get('responseTimeMs'),
            cached=True,
        )

    # Not in cache - return unknown
    url = get_job_url(index)
    return StatusResponse(
        index=index,
        url=url or '',
        status='UNKNOWN',
        source='generic',
        cached=False,
    )


@app.post("/api/jobs/{index}/check-status", response_model=StatusCheckResponse)
async def check_single_job_status(index: int):
    """
    Trigger a fresh status check for a single job.
    Returns immediately with the result.
    """
    url = get_job_url(index)
    if not url:
        raise HTTPException(status_code=404, detail=f"Job #{index} not found in manifest")

    # Perform the check
    result = await jsc.check_job_status(index, url)

    # Update cached status
    store = await load_status_store()
    store[index] = result.to_dict()
    await save_status_store(list(store.values()))

    return StatusCheckResponse(
        index=result.index,
        url=result.url,
        status=result.status,
        lastChecked=result.last_checked,
        error=result.error,
        source=result.source,
        httpStatusCode=result.http_status_code,
        responseTimeMs=result.response_time_ms,
    )


@app.post("/api/jobs/check-all", response_model=BatchCheckResponse)
async def check_all_jobs_status(background_tasks: BackgroundTasks):
    """
    Trigger batch status check for all jobs.
    This runs in the background and returns immediately.
    """
    jobs = get_all_jobs()
    if not jobs:
        return BatchCheckResponse(total=0, completed=0, results=[])

    # Run check in background task
    async def run_batch():
        logger.info(f"Starting batch check for {len(jobs)} jobs")
        results = await jsc.check_all_jobs(jobs, max_concurrent=5)

        # Update cached status
        store = await load_status_store()
        for result in results:
            store[result.index] = result.to_dict()
        await save_status_store(list(store.values()))

        logger.info(f"Batch check complete: {len(results)} jobs checked")

    background_tasks.add_task(run_batch)

    return BatchCheckResponse(
        total=len(jobs),
        completed=0,
        results=[],
    )


@app.get("/api/jobs/check-all/status")
async def get_batch_check_status():
    """
    Get current batch check status.
    Note: This is a simplified implementation. For full progress tracking,
    a more sophisticated approach with Redis or similar would be needed.
    """
    return JSONResponse({
        "message": "Batch check started. Use GET /api/jobs/{index}/status to check individual results.",
        "note": "Full progress tracking requires external state management.",
    })


@app.get("/api/jobs", response_model=list[StatusResponse])
async def list_all_jobs():
    """List all jobs with their cached status."""
    jobs = get_all_jobs()
    store = await load_status_store()

    result = []
    for index, url in jobs:
        if index in store:
            entry = store[index]
            result.append(StatusResponse(
                index=entry['index'],
                url=entry['url'],
                status=entry['status'],
                lastChecked=entry.get('lastChecked'),
                error=entry.get('error'),
                source=entry.get('source', 'generic'),
                httpStatusCode=entry.get('httpStatusCode'),
                responseTimeMs=entry.get('responseTimeMs'),
                cached=True,
            ))
        else:
            result.append(StatusResponse(
                index=index,
                url=url,
                status='UNKNOWN',
                source='generic',
                cached=False,
            ))

    return result


@app.put("/api/jobs/{index}/resume", response_model=MarkdownUpdateResponse)
async def update_resume(index: int, body: MarkdownUpdateRequest):
    """
    Update the resume markdown for a job.
    Creates a backup of the existing file before overwriting.
    """
    return await update_markdown_document(index, "resume", body.content)


@app.put("/api/jobs/{index}/cover-letter", response_model=MarkdownUpdateResponse)
async def update_cover_letter(index: int, body: MarkdownUpdateRequest):
    """
    Update the cover letter markdown for a job.
    Creates a backup of the existing file before overwriting.
    """
    return await update_markdown_document(index, "cover_letter", body.content)


async def update_markdown_document(index: int, doc_type: str, content: str) -> MarkdownUpdateResponse:
    """Shared logic for updating any markdown document."""
    bundle_dir = get_bundle_dir(index)
    if not bundle_dir:
        return MarkdownUpdateResponse(
            index=index,
            document=doc_type,
            saved=False,
            error=f"Job #{index}: bundle directory not found in applications/all_jobs/",
        )

    filename = "resume.md" if doc_type == "resume" else "cover_letter.md"
    doc_path = bundle_dir / filename

    if not doc_path.exists():
        return MarkdownUpdateResponse(
            index=index,
            document=doc_type,
            saved=False,
            error=f"Job #{index}: {filename} not found in bundle",
        )

    # Validate content
    if not content or not content.strip():
        return MarkdownUpdateResponse(
            index=index,
            document=doc_type,
            saved=False,
            error="Content cannot be empty",
        )

    if len(content) > MAX_CONTENT_SIZE:
        return MarkdownUpdateResponse(
            index=index,
            document=doc_type,
            saved=False,
            error=f"Content exceeds maximum size ({MAX_CONTENT_SIZE} bytes)",
        )

    # Create backup
    backup_path: Optional[str] = None
    try:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_file = doc_path.with_name(f"{doc_path.stem}.bak.{timestamp}{doc_path.suffix}")
        shutil.copy2(doc_path, backup_file)
        backup_path = str(backup_file)
        logger.info(f"Created backup: {backup_file}")
    except OSError as e:
        logger.warning(f"Could not create backup for {doc_path}: {e}")

    # Write new content
    try:
        doc_path.write_text(content, encoding="utf-8")
        logger.info(f"Updated {doc_path} for job #{index}")
        return MarkdownUpdateResponse(
            index=index,
            document=doc_type,
            saved=True,
            backup_path=backup_path,
        )
    except OSError as e:
        logger.error(f"Failed to write {doc_path}: {e}")
        return MarkdownUpdateResponse(
            index=index,
            document=doc_type,
            saved=False,
            error=f"Failed to write file: {e}",
        )


@app.post("/api/jobs/{index}/regenerate-resume", response_model=RegenerateResponse)
async def regenerate_resume_pdf(index: int):
    """
    Regenerate the resume PDF for a job from its markdown file.
    """
    return await regenerate_pdf(index, "resume")


@app.post("/api/jobs/{index}/regenerate-cl", response_model=RegenerateResponse)
async def regenerate_cover_letter_pdf(index: int):
    """
    Regenerate the cover letter PDF for a job from its markdown file.
    """
    return await regenerate_pdf(index, "cover_letter")


@app.post("/api/jobs/{index}/regenerate-pdf", response_model=RegenerateResponse)
async def regenerate_both_pdfs(index: int):
    """
    Regenerate both resume and cover letter PDFs for a job.
    Returns status for the resume; cover letter is regenerated in background.
    """
    # Regenerate resume first (synchronously)
    resume_result = await regenerate_pdf(index, "resume")

    # If resume succeeded, trigger cover letter in background
    if resume_result.success:
        async def regenerate_cl_background():
            await regenerate_pdf(index, "cover_letter")

        # We can't easily use BackgroundTasks here since we already returned,
        # so just regenerate cover letter synchronously too for now
        cl_result = await regenerate_pdf(index, "cover_letter")
        # Merge the results - resume is the primary response
        logger.info(f"Cover letter PDF regenerated for job #{index}")

    return resume_result


async def regenerate_pdf(index: int, doc_type: str) -> RegenerateResponse:
    """Shared logic for regenerating a PDF."""
    import time
    start_time = time.time()

    bundle_dir = get_bundle_dir(index)
    if not bundle_dir:
        return RegenerateResponse(
            index=index,
            document=doc_type,
            success=False,
            error=f"Job #{index}: bundle directory not found",
        )

    filename = "resume" if doc_type == "resume" else "cover_letter"
    input_path = bundle_dir / f"{filename}.md"
    if not input_path.exists():
        return RegenerateResponse(
            index=index,
            document=doc_type,
            success=False,
            error=f"Job #{index}: {filename}.md not found",
        )

    try:
        success, error = pdf_gen.generate_pdf(
            input_path=input_path,
            output_path=input_path.with_suffix(".pdf"),
            doc_type=doc_type,
            timeout=180,
        )

        duration_ms = int((time.time() - start_time) * 1000)

        if success:
            return RegenerateResponse(
                index=index,
                document=doc_type,
                success=True,
                pdf_path=str(input_path.with_suffix(".pdf")),
                duration_ms=duration_ms,
            )
        else:
            return RegenerateResponse(
                index=index,
                document=doc_type,
                success=False,
                error=error,
                duration_ms=duration_ms,
            )
    except Exception as e:
        logger.error(f"PDF regeneration failed for job #{index}: {e}")
        return RegenerateResponse(
            index=index,
            document=doc_type,
            success=False,
            error=str(e),
        )


@app.get("/api/jobs/{index}/pdf/{doc_type}")
async def get_pdf(index: int, doc_type: str):
    """
    Get a PDF file for a job.
    doc_type must be 'resume' or 'cover_letter'.
    """
    if doc_type not in ("resume", "cover_letter"):
        raise HTTPException(status_code=400, detail="doc_type must be 'resume' or 'cover_letter'")

    pdf_path = get_pdf_path(index, doc_type)
    if not pdf_path or not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"PDF not found for job #{index}")

    filename = "resume.pdf" if doc_type == "resume" else "cover_letter.pdf"
    return FileResponse(
        path=str(pdf_path),
        filename=filename,
        media_type="application/pdf",
    )


# ── Generation Restart Endpoints ─────────────────────────────────────────────

from generation.generation_orchestrator import (
    GenerationTarget,
    get_orchestrator,
)
from research.profile_service import get_profile_service


class GenerationStartRequest(BaseModel):
    """Request to start generation for a job."""
    target: str = Field(default="both", description="resume, cover_letter, or both")
    provider: str = Field(default="minimax", description="LLM provider to use")
    fallback_provider: Optional[str] = Field(default=None, description="Fallback provider")
    quality_policy: str = Field(default="advisory", description="Quality audit policy")


class GenerationStatusResponse(BaseModel):
    """Response with generation status."""
    job_index: int
    target: str
    status: str
    provider: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    progress_pct: float = 0.0
    current_step: str = ""
    estimated_remaining_s: Optional[float] = None
    error: Optional[str] = None
    output_dir: Optional[str] = None
    rubric_scores: Optional[dict] = None


@app.post("/api/jobs/{index}/generate", response_model=GenerationStatusResponse)
async def start_generation(index: int, body: GenerationStartRequest):
    """
    Start generation of resume and/or cover letter for a job.
    Returns immediately with initial status; generation runs in background.
    """
    # Validate target
    try:
        target = GenerationTarget(body.target)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid target: {body.target}. Must be 'resume', 'cover_letter', or 'both'."
        )

    # Validate provider
    valid_providers = ["minimax", "zai"]
    if body.provider not in valid_providers:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider: {body.provider}. Must be one of {valid_providers}."
        )

    orchestrator = get_orchestrator()

    # Check if job exists
    bundle_dir = get_bundle_dir(index)
    if not bundle_dir:
        raise HTTPException(status_code=404, detail=f"Job #{index}: bundle directory not found")

    try:
        get_profile_service().compile_active_profile()
        progress = await orchestrator.start_generation(
            job_index=index,
            target=target,
            provider=body.provider,
            fallback_provider=body.fallback_provider,
            quality_policy=body.quality_policy,
        )
        return GenerationStatusResponse(**progress.to_dict())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/api/jobs/{index}/generate/status", response_model=GenerationStatusResponse)
async def get_generation_status(index: int):
    """
    Get current generation status for a job.
    """
    orchestrator = get_orchestrator()
    progress = await orchestrator.get_status(index)
    return GenerationStatusResponse(**progress.to_dict())


@app.post("/api/jobs/{index}/generate/accept", response_model=GenerationStatusResponse)
async def accept_generation(index: int):
    """
    Accept generated content and promote it to the canonical bundle.
    """
    orchestrator = get_orchestrator()
    try:
        progress = await orchestrator.accept(index)
        return GenerationStatusResponse(**progress.to_dict())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/jobs/{index}/generate/reject", response_model=GenerationStatusResponse)
async def reject_generation(index: int):
    """
    Reject generated content and keep the old content.
    """
    orchestrator = get_orchestrator()
    try:
        progress = await orchestrator.reject(index)
        return GenerationStatusResponse(**progress.to_dict())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/jobs/{index}/generate/cancel", response_model=GenerationStatusResponse)
async def cancel_generation(index: int):
    """
    Cancel an in-progress generation.
    """
    orchestrator = get_orchestrator()
    try:
        progress = await orchestrator.cancel(index)
        return GenerationStatusResponse(**progress.to_dict())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/jobs/{index}/generate/content")
async def get_generation_content(index: int):
    """
    Get generated content (resume.md and cover_letter.md) from output_dir.
    Returns the content of both files for preview.
    """
    orchestrator = get_orchestrator()
    progress = await orchestrator.get_status(index)

    if not progress.output_dir:
        raise HTTPException(status_code=404, detail="No output directory found for this generation")

    output_path = Path(progress.output_dir)
    if not output_path.exists():
        raise HTTPException(status_code=404, detail=f"Output directory not found: {progress.output_dir}")

    result = {}
    for doc_type in ["resume", "cover_letter"]:
        file_path = output_path / f"{doc_type}.md"
        if file_path.exists():
            result[doc_type] = file_path.read_text(encoding="utf-8")
        else:
            result[doc_type] = None

    return JSONResponse({
        "job_index": index,
        "output_dir": progress.output_dir,
        "content": result,
    })


# ── Profile Endpoints ────────────────────────────────────────────────────────

class SkillCatalogCreateRequest(BaseModel):
    """Request to create a custom skill-catalog entry."""
    name: str = Field(..., min_length=1, max_length=200)


@app.get("/api/profile")
async def get_active_profile():
    """Return the active structured profile, bootstrapping one if needed."""
    return get_profile_service().get_active_profile().model_dump()


@app.put("/api/profile")
async def save_active_profile(body: dict = Body(...)):
    """Save the active profile and recompile generator facts."""
    profile, compile_result = get_profile_service().save_active_profile(body)
    return {
        "profile": profile.model_dump(),
        "compile_result": compile_result.model_dump(),
    }


@app.get("/api/profile/skills/catalog")
async def search_profile_skill_catalog(
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Search the structured profile skill catalog."""
    entries = get_profile_service().search_skill_catalog(q, limit)
    return [entry.model_dump() for entry in entries]


@app.post("/api/profile/skills/catalog")
async def create_profile_skill_catalog_entry(body: SkillCatalogCreateRequest):
    """Create a custom skill-catalog entry."""
    entry = get_profile_service().create_skill_catalog_entry(body.name)
    return entry.model_dump()


# ── Source Record Endpoints ─────────────────────────────────────────────────

from source_service import get_source_service, SourceSuggestionModel


class CreateSourceRequest(BaseModel):
    """Request to create a new source record."""
    archetype: str = Field(..., description="new_grad or experienced")
    label: str = Field(..., min_length=1, max_length=200)


class UpdateSourceRequest(BaseModel):
    """Request to update a source record's fields."""
    label: Optional[str] = None
    fields: list[dict] = Field(default_factory=list)


class NoteExtractionRequest(BaseModel):
    """Request to extract suggestions from freeform notes."""
    note_text: str = Field(..., min_length=1, max_length=50000)


class ApplySuggestionRequest(BaseModel):
    """Request to apply a single suggestion."""
    suggestion_id: str
    record_id: str
    field_id: str
    field_label: str
    current_value: str
    suggested_value: str
    confidence: float
    source_note: str


class BatchNormalizeRequest(BaseModel):
    """Request for batch normalization across all source records."""
    note_text: str = Field(..., min_length=1, max_length=50000)
    auto_apply: bool = False
    min_confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class BatchNormalizeResponse(BaseModel):
    """Response from the batch normalization trigger."""
    status: str
    records_scanned: int
    total_suggestions: int = 0
    auto_applied: int = 0
    pending_review: int = 0


@app.get("/api/sources/archetypes")
async def list_archetypes():
    """Return all archetype definitions with their field schemas."""
    svc = get_source_service()
    return svc.list_archetypes()


@app.get("/api/sources/archetypes/{archetype}")
async def get_archetype(archetype: str):
    """Return a single archetype definition."""
    svc = get_source_service()
    result = svc.get_archetype(archetype)
    if not result:
        raise HTTPException(status_code=404, detail=f"Archetype '{archetype}' not found")
    return result


@app.get("/api/sources/records")
async def list_source_records():
    """Return all source records with their field values."""
    svc = get_source_service()
    records = await svc.list_records_async()
    return [r.model_dump() for r in records]


@app.post("/api/sources/records")
async def create_source_record(body: CreateSourceRequest):
    """Create a new source record with empty archetype fields."""
    svc = get_source_service()
    try:
        record = await svc.create_record_async(archetype=body.archetype, label=body.label)
        return record.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/sources/records/{record_id}")
async def get_source_record(record_id: str):
    """Return a single source record by ID."""
    svc = get_source_service()
    record = await svc.get_record_async(record_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Record '{record_id}' not found")
    return record.model_dump()


@app.put("/api/sources/records/{record_id}")
async def update_source_record(record_id: str, body: UpdateSourceRequest):
    """Update a source record's fields and create a revision."""
    svc = get_source_service()
    record = await svc.update_record_async(
        record_id=record_id,
        label=body.label,
        fields=body.fields,
    )
    if not record:
        raise HTTPException(status_code=404, detail=f"Record '{record_id}' not found")
    return record.model_dump()


@app.delete("/api/sources/records/{record_id}")
async def delete_source_record(record_id: str):
    """Delete a source record and all associated data."""
    svc = get_source_service()
    if not await svc.delete_record_async(record_id):
        raise HTTPException(status_code=404, detail=f"Record '{record_id}' not found")
    return {"deleted": True, "record_id": record_id}


@app.get("/api/sources/records/{record_id}/revisions")
async def list_source_revisions(record_id: str):
    """Return revision history for a source record."""
    svc = get_source_service()
    record = await svc.get_record_async(record_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Record '{record_id}' not found")
    revisions = await svc.list_revisions_async(record_id)
    # Omit the snapshot blob from the list response
    return [
        {
            "revision_id": r.revision_id,
            "record_id": r.record_id,
            "created_at": r.created_at,
            "provenance": r.provenance,
            "summary": r.summary,
            "field_count": r.field_count,
        }
        for r in revisions
    ]


@app.post("/api/sources/records/{record_id}/extract")
async def extract_note_to_source(record_id: str, body: NoteExtractionRequest):
    """Extract structured suggestions from freeform notes."""
    svc = get_source_service()
    try:
        result = await svc.extract_suggestions_async(record_id, body.note_text)
        return result.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/sources/suggestions/apply")
async def apply_suggestion(body: ApplySuggestionRequest):
    """Apply a single suggestion, updating the record."""
    svc = get_source_service()
    suggestion = SourceSuggestionModel(
        suggestion_id=body.suggestion_id,
        record_id=body.record_id,
        field_id=body.field_id,
        field_label=body.field_label,
        current_value=body.current_value,
        suggested_value=body.suggested_value,
        confidence=body.confidence,
        source_note=body.source_note,
    )
    record = await svc.apply_suggestion_async(suggestion)
    if not record:
        raise HTTPException(status_code=404, detail=f"Record '{body.record_id}' not found")
    return record.model_dump()


@app.post("/api/sources/normalize", response_model=BatchNormalizeResponse)
async def batch_normalize(body: BatchNormalizeRequest, background_tasks: BackgroundTasks):
    """
    Trigger background normalization: extract suggestions from a note
    across all records. High-confidence suggestions can be auto-applied.
    Returns immediately with initial counts; processing runs in background.
    """
    svc = get_source_service()
    records = await svc.list_records_async()

    async def run_normalization() -> None:
        total_suggestions = 0
        auto_applied = 0
        for record in records:
            try:
                result = await svc.extract_suggestions_async(record.record_id, body.note_text)
                total_suggestions += len(result.suggestions)
                if body.auto_apply:
                    for sug in result.suggestions:
                        if sug.confidence >= body.min_confidence:
                            await svc.apply_suggestion_async(sug)
                            auto_applied += 1
            except Exception as exc:
                logger.warning(f"Normalization failed for record {record.record_id}: {exc}")
        logger.info(
            f"Batch normalization complete: {total_suggestions} suggestions, "
            f"{auto_applied} auto-applied"
        )

    background_tasks.add_task(run_normalization)

    return BatchNormalizeResponse(
        status="started",
        records_scanned=len(records),
    )


# ── Search Endpoints ───────────────────────────────────────────────────────────

from search import get_search_store, SearchPreferenceModel, JobListModel, JobListDetailModel
from search.search_service import start_search_run


class CreatePreferenceRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=200)
    archetype: str = Field(..., description="new_grad or experienced")
    keywords: list[str] = Field(..., min_length=1)
    locations: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    experience_level: Optional[str] = None
    remote_policy: Optional[str] = None
    salary_min: Optional[int] = None


class StartRunRequest(BaseModel):
    preference_id: str


@app.get("/api/search/preferences")
async def list_preferences():
    """Return all saved search preferences."""
    store = get_search_store()
    prefs = store.list_preferences()
    return [p.model_dump() for p in prefs]


@app.post("/api/search/preferences")
async def create_preference(body: CreatePreferenceRequest):
    """Create a new search preference."""
    store = get_search_store()
    pref = store.create_preference(
        label=body.label,
        archetype=body.archetype,
        keywords=body.keywords,
        locations=body.locations,
        sources=body.sources,
        experience_level=body.experience_level,
        remote_policy=body.remote_policy,
        salary_min=body.salary_min,
    )
    return pref.model_dump()


@app.delete("/api/search/preferences/{preference_id}")
async def delete_preference(preference_id: str):
    """Delete a search preference and its associated runs."""
    store = get_search_store()
    if not store.delete_preference(preference_id):
        raise HTTPException(status_code=404, detail=f"Preference '{preference_id}' not found")
    return {"deleted": True, "preference_id": preference_id}


@app.get("/api/search/runs")
async def list_runs():
    """Return all search runs (newest first), without candidate lists."""
    store = get_search_store()
    runs = store.list_runs()
    return [r.model_dump() for r in runs]


@app.post("/api/search/runs")
async def start_run(body: StartRunRequest):
    """Start a new search run for a given preference. Returns immediately."""
    store = get_search_store()
    pref = store.get_preference(body.preference_id)
    if not pref:
        raise HTTPException(status_code=404, detail=f"Preference '{body.preference_id}' not found")

    run_id = start_search_run(pref)
    run = store.get_run(run_id)
    return run.model_dump() if run else {"run_id": run_id, "status": "pending"}


@app.get("/api/search/runs/{run_id}")
async def get_run_detail(run_id: str):
    """Return a single run with its full candidate list."""
    store = get_search_store()
    detail = store.get_run_detail(run_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return detail.model_dump()


@app.post("/api/search/candidates/{candidate_id}/ingest")
async def ingest_candidate(candidate_id: str):
    """Ingest a candidate into the canonical inventory and mark local search state."""
    store = get_search_store()
    candidate = store.get_candidate(candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail=f"Candidate '{candidate_id}' not found")

    try:
        ingest_result = await ingest_candidate_into_canonical_inventory(
            candidate,
            settings=get_runtime_settings(),
            load_jobs_manifest=load_jobs_manifest,
        )
    except CanonicalIngestRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except CanonicalIngestConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("Canonical candidate ingest failed for %s: %s", candidate_id, exc)
        raise HTTPException(status_code=500, detail="Canonical ingest failed")

    store.mark_candidate_ingested(candidate_id)
    return {
        "candidate_id": candidate_id,
        "ingested": True,
        **ingest_result.to_dict(),
    }


# ── List Endpoints ────────────────────────────────────────────────────────────

class ReorderItemsRequest(BaseModel):
    item_ids: list[str]


class UpdateItemNotesRequest(BaseModel):
    notes: str


class UpdateItemPriorityRequest(BaseModel):
    priority: str


class UpdateItemStatusRequest(BaseModel):
    status: str


@app.get("/api/search/lists")
async def list_lists():
    """Return all curated job lists."""
    store = get_search_store()
    lists = store.list_lists()
    return [lst.model_dump() for lst in lists]


@app.get("/api/search/lists/{list_id}")
async def get_list(list_id: str):
    """Return a list with its full ordered items and denormalized candidate data."""
    store = get_search_store()
    detail = store.get_list_detail(list_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"List '{list_id}' not found")

    research_store = get_research_store()
    items = []
    for item in detail.items:
        company_key = compute_company_key(item.company)
        company_research = research_store.get_company_detail(company_key)
        item_payload = item.model_dump()
        item_payload["fit_score"] = round(1.0 / (1 + max(0, item.search_rank)), 3)
        item_payload["research_summary"] = {
            "has_research": company_research is not None,
            "claim_count": len(company_research["claims"]) if company_research else 0,
            "question_count": len(company_research["questions"]) if company_research else 0,
            "last_refreshed_at": company_research["last_refreshed_at"] if company_research else None,
            "is_stale": company_research["is_stale"] if company_research else False,
        }
        items.append(item_payload)

    payload = detail.model_dump()
    payload["items"] = items
    return payload


@app.get("/api/search/runs/{run_id}/list")
async def get_list_for_run(run_id: str):
    """Return the curated list associated with a search run."""
    store = get_search_store()
    lst = store.get_list_for_run(run_id)
    if not lst:
        raise HTTPException(status_code=404, detail=f"No list found for run '{run_id}'")
    return lst.model_dump()


@app.delete("/api/search/lists/items/{item_id}")
async def remove_list_item(item_id: str):
    """Remove an item from its list (does not delete the candidate)."""
    store = get_search_store()
    if not store.remove_item(item_id):
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found")
    return {"item_id": item_id, "removed": True}


@app.patch("/api/search/lists/items/reorder")
async def reorder_list_items(body: ReorderItemsRequest):
    """
    Reorder items within a list.
    item_ids must contain ALL item_ids for the list in their new positional order.
    """
    if not body.item_ids:
        raise HTTPException(status_code=400, detail="item_ids cannot be empty")

    store = get_search_store()
    # Get the list_id from the first item
    first_item = store.get_item(body.item_ids[0])
    if not first_item:
        raise HTTPException(status_code=404, detail="Item not found")
    store.reorder_items(first_item.list_id, body.item_ids)
    return {"list_id": first_item.list_id, "reordered": True}


@app.patch("/api/search/lists/items/{item_id}/notes")
async def update_item_notes(item_id: str, body: UpdateItemNotesRequest):
    """Update notes on a list item."""
    store = get_search_store()
    if not store.update_item_notes(item_id, body.notes):
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found")
    return {"item_id": item_id, "notes": body.notes}


@app.patch("/api/search/lists/items/{item_id}/priority")
async def update_item_priority(item_id: str, body: UpdateItemPriorityRequest):
    """Update priority on a list item (low | medium | high)."""
    if body.priority not in ("low", "medium", "high"):
        raise HTTPException(status_code=400, detail="priority must be low, medium, or high")
    store = get_search_store()
    if not store.update_item_priority(item_id, body.priority):
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found")
    return {"item_id": item_id, "priority": body.priority}


@app.patch("/api/search/lists/items/{item_id}/status")
async def update_item_status(item_id: str, body: UpdateItemStatusRequest):
    """Update status on a list item (wishlist | applied | rejected)."""
    if body.status not in ("wishlist", "applied", "rejected"):
        raise HTTPException(status_code=400, detail="status must be wishlist, applied, or rejected")
    store = get_search_store()
    if not store.update_item_status(item_id, body.status):
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found")
    return {"item_id": item_id, "status": body.status}


@app.post("/api/search/lists/items/{item_id}/promote")
async def promote_list_item(item_id: str):
    """
    Promote a list item to the canonical application inventory.
    Performs canonical ingest before marking the item as promoted.
    """
    store = get_search_store()
    item = store.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found")

    candidate = store.get_candidate(item.candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail=f"Candidate '{item.candidate_id}' not found")

    try:
        ingest_result = await ingest_candidate_into_canonical_inventory(
            candidate,
            settings=get_runtime_settings(),
            load_jobs_manifest=load_jobs_manifest,
        )
    except CanonicalIngestRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except CanonicalIngestConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("Canonical list promotion failed for %s: %s", item_id, exc)
        raise HTTPException(status_code=500, detail="Canonical promotion failed")

    store.mark_candidate_ingested(item.candidate_id)
    store.mark_item_promoted(item_id)
    return {
        "item_id": item_id,
        "candidate_id": item.candidate_id,
        "promoted": True,
        **ingest_result.to_dict(),
    }


# ── Research Endpoints ───────────────────────────────────────────────────────

from research import get_research_store, compute_company_key, start_research_refresh


@app.get("/api/research/companies")
async def list_research_companies():
    """Return all companies with research summary data."""
    store = get_research_store()
    return store.list_companies()


@app.get("/api/research/company/{company_key}")
async def get_company_research(company_key: str):
    """Return full company research with claims, questions, and snapshots."""
    store = get_research_store()
    detail = store.get_company_detail(company_key)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Company '{company_key}' not found")
    return detail


@app.get("/api/research/company/{company_key}/snapshots")
async def list_company_snapshots(company_key: str):
    """Return snapshot history for a company."""
    store = get_research_store()
    company = store.get_company_detail(company_key)
    if not company:
        raise HTTPException(status_code=404, detail=f"Company '{company_key}' not found")
    return store.list_snapshots(company_key)


@app.post("/api/research/company/{company_key}/refresh")
async def trigger_company_refresh(company_key: str):
    """
    Trigger a research refresh for a company.
    Creates a new timestamped snapshot. Returns immediately with refresh_id.
    """
    store = get_research_store()

    # Derive company name from key if company exists, otherwise use key
    company_name = store.get_company_name(company_key)
    if not company_name:
        company_name = company_key.replace("-", " ").title()

    refresh_id = start_research_refresh(company_key, company_name)
    refresh = store.get_refresh(refresh_id)

    return {
        "refresh_id": refresh_id,
        "company_key": company_key,
        "status": "pending",
        "started_at": refresh.started_at if refresh else _utc_now(),
    }


@app.get("/api/research/refresh/{refresh_id}")
async def get_refresh_status(refresh_id: str):
    """Return current status of a research refresh."""
    store = get_research_store()
    refresh = store.get_refresh(refresh_id)
    if not refresh:
        raise HTTPException(status_code=404, detail=f"Refresh '{refresh_id}' not found")
    return refresh.model_dump()


# ── Graph Memory Endpoints ───────────────────────────────────────────────────

import re


@app.get("/api/graph/health")
async def graph_health():
    """Return graph worker health and event statistics."""
    service = get_career_graph_service()
    return service.health().model_dump()


@app.get("/api/graph/company/{company_key}/history")
async def graph_company_history(company_key: str):
    """Return graph-backed career memory for a specific company.

    company_key must contain only alphanumeric characters, hyphens, and underscores.
    """
    if not re.match(r"^[a-zA-Z0-9_-]+$", company_key):
        raise HTTPException(
            status_code=400,
            detail="company_key must contain only alphanumeric characters, hyphens, and underscores",
        )
    service = get_career_graph_service()
    result = await service.query_company_history(company_key)
    return result.model_dump()


@app.get("/api/graph/search/history")
async def graph_search_history(limit: int = Query(default=20, ge=1, le=100)):
    """Return graph-backed search history with company aggregation.

    limit is clamped to [1, 100].
    """
    service = get_career_graph_service()
    result = await service.query_search_history(limit=limit)
    return result.model_dump()


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
