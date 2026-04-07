"""
Chat Backend - FastAPI Chat Server

Provides text chat with vLLM Nanbeige, TTS synthesis, and job context endpoints.

Endpoints:
- POST /api/chat         : Send message, get LLM response
- POST /api/tts          : Convert text to audio
- GET  /api/jobs         : List all jobs
- GET  /api/jobs/{idx}/context : Get resume + cover letter for a job
- GET  /health           : Health check

Run with: uvicorn chat.chat_backend:app --port 8080
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from agent.agent_runner import (
    AgentPathSafetyError,
    AgentRunner,
    get_agent_circuit_breaker,
)
from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from jobs.job_context import get_bundle_dir, get_job_context, get_job_list, get_job_name
from llm.llm_client import VLLMCircuitOpenError, VLLMClient
from pydantic import BaseModel, Field
from research.profile_service import get_profile_service
from voice.tts_cache import TTSCache
from voice.tts_client import VibeVoiceTTSClient, synthesize_speech
from voice.voice_clone_service import VoiceCloneService

_logger = logging.getLogger(__name__)

# Configuration
PORT = int(os.environ.get("PORT", "8080"))

# Skills directory - at project root (same level as chat_backend.py)
SKILLS_DIR = Path(__file__).parent / "skills"
MAX_HISTORY_TURNS = 10

# SQLite session database
SESSION_DB = Path(__file__).parent / ".sessions.db"


def load_skill(name: str) -> dict | None:
    """Load a skill YAML file by name.

    Loads fresh per-call (not cached) so edits take effect immediately.

    Args:
        name: Skill filename (e.g., 'resume_default.yaml')

    Returns:
        Parsed skill dict or None if not found/error
    """
    path = SKILLS_DIR / name
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        _logger.warning(f"Failed to load skill: {name}")
        return None


def init_session_db():
    """Create session tables if they don't exist with WAL mode for ACID compliance."""
    with sqlite3.connect(SESSION_DB) as conn:
        # Enable WAL mode for better concurrent access and ACID guarantees
        conn.execute("PRAGMA journal_mode=WAL")
        # Set busy timeout to 5 seconds to prevent 'database is locked' errors
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                job_index INTEGER,
                skill_name TEXT,
                skill_job_type TEXT,
                messages TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS session_metadata (
                session_id TEXT PRIMARY KEY,
                display_name TEXT,
                message_count INTEGER DEFAULT 0,
                skill_job_type TEXT
            )
        """)


def save_session(session_id: str, messages: list[dict], job_index: int | None, skill_name: str | None, skill_job_type: str | None = None):
    """Persist session to SQLite."""
    now = time.time()
    with sqlite3.connect(SESSION_DB) as conn:
        # Check if session exists to get created_at
        row = conn.execute("SELECT created_at FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        created_at = row[0] if row else now

        conn.execute("""
            INSERT OR REPLACE INTO sessions (session_id, created_at, updated_at, job_index, skill_name, skill_job_type, messages)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (session_id, created_at, now, job_index, skill_name, skill_job_type, json.dumps(messages)))

        conn.execute("""
            INSERT OR REPLACE INTO session_metadata (session_id, display_name, message_count, skill_job_type)
            VALUES (?, ?, ?, ?)
        """, (session_id, f"Session {session_id[:4]}", len(messages), skill_job_type))


def load_session(session_id: str) -> tuple[list[dict], int | None, str | None, str | None] | None:
    """Load session from SQLite. Returns (messages, job_index, skill_name, skill_job_type) or None."""
    with sqlite3.connect(SESSION_DB) as conn:
        row = conn.execute(
            "SELECT messages, job_index, skill_name, skill_job_type FROM sessions WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        if row:
            return json.loads(row[0]), row[1], row[2], row[3]
    # Also trim old sessions on load
    trim_sessions()
    return None


def list_sessions() -> list[dict]:
    """List all sessions ordered by most recently updated."""
    with sqlite3.connect(SESSION_DB) as conn:
        # Trim old sessions on list
        trim_sessions()
        rows = conn.execute("""
            SELECT s.session_id, s.updated_at, s.job_index, s.skill_name, s.skill_job_type,
                   COALESCE(m.display_name, s.session_id) as display_name,
                   COALESCE(m.message_count, 0) as message_count
            FROM sessions s
            LEFT JOIN session_metadata m ON s.session_id = m.session_id
            ORDER BY s.updated_at DESC
        """).fetchall()
        return [
            {
                "session_id": r[0],
                "updated_at": r[1],
                "job_index": r[2],
                "skill_name": r[3],
                "skill_job_type": r[4],
                "display_name": r[5],
                "message_count": r[6]
            }
            for r in rows
        ]


def trim_sessions():
    """Delete sessions older than 30 days to enforce retention policy."""
    cutoff = time.time() - (30 * 24 * 60 * 60)  # 30 days ago
    with sqlite3.connect(SESSION_DB) as conn:
        conn.execute("DELETE FROM sessions WHERE updated_at < ?", (cutoff,))
        conn.execute("DELETE FROM session_metadata WHERE session_id NOT IN (SELECT session_id FROM sessions)")


# --- Pydantic Models ---

class ChatRequest(BaseModel):
    """Request for /api/chat endpoint."""
    message: str = Field(..., min_length=1, max_length=10000)
    job_index: int | None = None
    session_id: str | None = None
    skill_name: str | None = None  # which skill to use as system prompt override


class ChatResponse(BaseModel):
    """Response for /api/chat endpoint."""
    response: str
    session_id: str


class AgentRequest(BaseModel):
    """Request for /api/agent endpoint."""
    instruction: str = Field(..., min_length=1, max_length=5000)
    job_index: int | None = None
    session_id: str | None = None


class AgentResponse(BaseModel):
    """Response for /api/agent endpoint."""
    success: bool
    response: str
    checkpoint_id: str | None = None
    error: str | None = None
    circuit_breaker_open: bool = False
    iterations_used: int = 0
    timeout_occurred: bool = False
    resets_in_s: int = 0


class RollbackRequest(BaseModel):
    """Request for /api/agent/rollback endpoint."""
    checkpoint_id: str = Field(..., min_length=1)


class RollbackResponse(BaseModel):
    """Response for /api/agent/rollback endpoint."""
    success: bool
    restored_content: str | None = None
    error: str | None = None


class TTSRequest(BaseModel):
    """Request for /api/tts endpoint."""
    text: str = Field(..., min_length=1, max_length=5000)
    voice: str = "carter"


class VoiceCloneRequest(BaseModel):
    """Request for /api/voice-clone endpoint."""
    name: str = Field(default="user_voice", min_length=1, max_length=50)


class VoiceCloneResponse(BaseModel):
    """Response for /api/voice-clone endpoint."""
    success: bool
    name: str
    message: str


class VoiceInfo(BaseModel):
    """Single voice entry."""
    id: str
    name: str
    type: str  # "preset" or "cloned"
    size_kb: float | None = None


class VoiceListResponse(BaseModel):
    """Response for /api/voices endpoint."""
    voices: list[VoiceInfo]


class EngineStatusResponse(BaseModel):
    """Response for /api/tts/engine/status endpoint."""
    state: str
    moss_loaded: bool
    vram: dict | None = None


class JobContextResponse(BaseModel):
    """Response for /api/jobs/{index}/context endpoint."""
    resume: str
    cover_letter: str
    job_name: str


class JobInfo(BaseModel):
    """Single job entry."""
    index: int
    name: str


class JobListResponse(BaseModel):
    """Response for /api/jobs endpoint."""
    jobs: list[JobInfo]


class HealthResponse(BaseModel):
    """Response for /health endpoint."""
    status: str
    vllm_healthy: bool


class SkillFile(BaseModel):
    """Single skill file entry."""
    name: str
    modified: float
    size: int


class SkillListResponse(BaseModel):
    """Response for /api/skills endpoint."""
    skills: list[SkillFile]


class SkillResponse(BaseModel):
    """Response for single skill file."""
    content: str
    name: str


class SaveResponse(BaseModel):
    """Response for save skill endpoint."""
    status: str = "saved"
    backup: str | None


class SkillVersion(BaseModel):
    """Single version entry."""
    name: str
    modified: float
    current: bool


class VersionsResponse(BaseModel):
    """Response for versions endpoint."""
    versions: list[SkillVersion]


class SessionInfo(BaseModel):
    """Single session entry for list endpoint."""
    session_id: str
    updated_at: float
    job_index: int | None
    skill_name: str | None
    skill_job_type: str | None
    display_name: str
    message_count: int


class SessionListResponse(BaseModel):
    """Response for /api/sessions endpoint."""
    sessions: list[SessionInfo]


class SessionLoadResponse(BaseModel):
    """Response for /api/sessions/{session_id} endpoint."""
    session_id: str
    messages: list[dict[str, str]]
    job_index: int | None
    skill_name: str | None
    skill_job_type: str | None


# --- Global clients (initialized on startup) ---

_llm_client: VLLMClient | None = None
_tts_client: VibeVoiceTTSClient | None = None
_agent_runner: AgentRunner | None = None
_tts_cache: TTSCache | None = None


def get_llm() -> VLLMClient:
    """Get or create the global LLM client."""
    global _llm_client
    if _llm_client is None:
        _llm_client = VLLMClient()
    return _llm_client


def get_tts() -> VibeVoiceTTSClient:
    """Get or create the global TTS client."""
    global _tts_client
    if _tts_client is None:
        _tts_client = VibeVoiceTTSClient()
    return _tts_client


def get_agent_runner() -> AgentRunner:
    """Get or create the global agent runner."""
    global _agent_runner
    if _agent_runner is None:
        _agent_runner = AgentRunner(
            project_root=Path(__file__).parent,
            checkpoint_dir=Path(__file__).parent / ".agent_checkpoints",
        )
    return _agent_runner


def get_tts_cache() -> TTSCache:
    """Get or create the global TTS cache."""
    global _tts_cache
    if _tts_cache is None:
        _tts_cache = TTSCache()
    return _tts_cache


_voice_clone_service: VoiceCloneService | None = None


def get_voice_clone_service() -> VoiceCloneService:
    """Get or create the global voice clone service."""
    global _voice_clone_service
    if _voice_clone_service is None:
        _voice_clone_service = VoiceCloneService()
    return _voice_clone_service


# --- FastAPI App ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan."""
    # Startup
    _logger.info("Chat backend starting up...")
    init_session_db()
    get_tts_cache()  # Initialize TTS cache
    trim_sessions()  # Enforce 30-day retention on startup
    yield
    # Shutdown
    if _llm_client:
        await _llm_client.aclose()
    _logger.info("Chat backend shut down")


app = FastAPI(
    title="Chat Backend",
    description="Text chat with vLLM Nanbeige + TTS + Job Context",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware - allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- API Endpoints ---

@app.get("/api/skills", response_model=SkillListResponse)
async def list_skills() -> SkillListResponse:
    """List all available skill files (excluding .bak files).

    Returns:
        SkillListResponse with list of skill files sorted by modified time (newest first)
    """
    SKILLS_DIR.mkdir(exist_ok=True)
    skills = []
    for p in SKILLS_DIR.glob("*.yaml"):
        if not p.name.endswith('.bak'):
            skills.append(SkillFile(
                name=p.name,
                modified=p.stat().st_mtime,
                size=p.stat().st_size,
            ))
    skills.sort(key=lambda s: s.modified, reverse=True)
    return SkillListResponse(skills=skills)


@app.get("/api/skills/{filename}", response_model=SkillResponse)
async def get_skill(filename: str):
    """Get skill file content.

    Args:
        filename: Name of the skill file (e.g., 'resume_default.yaml')

    Returns:
        SkillResponse with file content and name

    Raises:
        HTTPException: 404 if file not found
    """
    # Validate filename - only allow .yaml extension
    if not filename.endswith('.yaml'):
        raise HTTPException(status_code=400, detail="Skill files must have .yaml extension")

    path = SKILLS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Skill '{filename}' not found")

    return SkillResponse(
        content=path.read_text(encoding="utf-8"),
        name=filename,
    )


@app.put("/api/skills/{filename}")
async def save_skill(filename: str, content: str = Body(..., media_type="text/plain")):
    """Save skill with backup. Creates .bak of previous version.

    Before writing, if the file already exists, it is copied to {filename}.bak

    Args:
        filename: Name of the skill file
        content: New file content (plain text)

    Returns:
        SaveResponse with status and backup path if created
    """
    # Validate filename
    if not filename.endswith('.yaml'):
        raise HTTPException(status_code=400, detail="Skill files must have .yaml extension")

    SKILLS_DIR.mkdir(exist_ok=True)
    path = SKILLS_DIR / filename
    backup_path = None

    # Create backup of existing file
    if path.exists():
        backup_path = path.with_suffix('.yaml.bak')
        shutil.copy2(path, backup_path)

    # Write new content
    path.write_text(content, encoding="utf-8")

    return SaveResponse(status="saved", backup=str(backup_path) if backup_path else None)


@app.get("/api/skills/{filename}/versions", response_model=VersionsResponse)
async def get_skill_versions(filename: str):
    """List available versions for a skill file.

    Returns current version and .bak backup if it exists.

    Args:
        filename: Name of the skill file

    Returns:
        VersionsResponse with list of versions (current + backup if exists)
    """
    if not filename.endswith('.yaml'):
        raise HTTPException(status_code=400, detail="Skill files must have .yaml extension")

    versions = []
    current = SKILLS_DIR / filename
    bak = SKILLS_DIR / f"{filename}.bak"

    if current.exists():
        versions.append(SkillVersion(
            name=filename,
            modified=current.stat().st_mtime,
            current=True,
        ))

    if bak.exists():
        versions.append(SkillVersion(
            name=f"{filename}.bak",
            modified=bak.stat().st_mtime,
            current=False,
        ))

    # Sort by modified time, newest first
    versions.sort(key=lambda v: v.modified, reverse=True)
    return VersionsResponse(versions=versions)


@app.get("/api/skills/{filename}/content/{version_name}", response_model=SkillResponse)
async def get_skill_version_content(filename: str, version_name: str):
    """Get content of a specific version of a skill file.

    Args:
        filename: Name of the original skill file
        version_name: Name of the version file (e.g., 'resume_default.yaml.bak')

    Returns:
        SkillResponse with version file content

    Raises:
        HTTPException: 404 if version file not found
    """
    # Validate version_name to prevent path traversal
    if '..' in version_name or '/' in version_name or '\\' in version_name:
        raise HTTPException(status_code=400, detail="Invalid version name")

    path = SKILLS_DIR / version_name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Version '{version_name}' not found")

    return SkillResponse(
        content=path.read_text(encoding="utf-8"),
        name=version_name,
    )


@app.get("/api/sessions", response_model=SessionListResponse)
async def list_sessions_endpoint():
    """List all saved sessions ordered by most recently updated."""
    sessions = list_sessions()
    return SessionListResponse(sessions=sessions)


@app.get("/api/sessions/{session_id}", response_model=SessionLoadResponse)
async def get_session(session_id: str):
    """Load a specific session's messages and context."""
    result = load_session(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found")
    messages, job_index, skill_name, skill_job_type = result
    return SessionLoadResponse(
        session_id=session_id,
        messages=messages,
        job_index=job_index,
        skill_name=skill_name,
        skill_job_type=skill_job_type
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Send a chat message and receive an LLM response.

    Args:
        request.message: The user's message
        request.job_index: Optional job index to inject resume/cover letter context
        request.session_id: Optional session ID for conversation history

    Returns:
        ChatResponse with the LLM's response and session_id
    """
    # Get or create session
    session_id = request.session_id
    if session_id is None:
        session_id = str(uuid.uuid4())[:8]

    result = load_session(session_id)
    if result is not None:
        history, _, _, _ = result
    else:
        history = []

    # Build context with optional job context
    context_messages: list[dict[str, str]] = []

    profile_context = get_profile_service().build_profile_context()
    if profile_context.strip():
        context_messages.append({
            "role": "system",
            "content": f"Use the active applicant profile as the source of truth when answering:\n\n{profile_context}",
        })

    # Add job context if provided
    if request.job_index is not None:
        job_ctx = get_job_context(request.job_index)
        job_name = get_job_name(request.job_index)

        if job_ctx["resume"] or job_ctx["cover_letter"]:
            context_parts = []
            if job_ctx["resume"]:
                context_parts.append(f"RESUME:\n{job_ctx['resume']}")
            if job_ctx["cover_letter"]:
                context_parts.append(f"COVER LETTER:\n{job_ctx['cover_letter']}")

            if context_parts:
                context_text = "\n\n".join(context_parts)
                context_messages.append({
                    "role": "system",
                    "content": f"You are helping with a job application for '{job_name}'. Here is the applicant's documents:\n\n{context_text}"
                })

    # Inject skill system prompt if specified
    if request.skill_name:
        skill = load_skill(request.skill_name)
        if skill and skill.get("prompts", {}).get("system"):
            # Prepend skill system prompt to context
            context_messages.insert(0, {
                "role": "system",
                "content": skill["prompts"]["system"]
            })

    # Add recent history (up to MAX_HISTORY_TURNS)
    for msg in history[-MAX_HISTORY_TURNS:]:
        context_messages.append(msg)

    # Add current message
    context_messages.append({"role": "user", "content": request.message})

    # Call LLM
    llm = get_llm()
    try:
        response_text = await llm.complete_text(
            user_text=request.message,
            context=context_messages if len(context_messages) > 1 else None,
        )
    except VLLMCircuitOpenError:
        _logger.warning(f"Circuit breaker open for session {session_id}")
        response_text = "Sorry, the AI service is temporarily unavailable. Please try again later."
    except Exception as exc:
        _logger.error(f"LLM error: {exc}")
        response_text = "Sorry, I encountered an error processing your request."

    # Update history
    history.append({"role": "user", "content": request.message})
    history.append({"role": "assistant", "content": response_text})
    save_session(session_id, history, request.job_index, request.skill_name, None)

    return ChatResponse(response=response_text, session_id=session_id)


@app.post("/api/agent", response_model=AgentResponse)
async def agent(request: AgentRequest) -> AgentResponse:
    """Execute a natural language file operation via Claude Code agent.

    The agent is sandboxed to applications/{job_id}/, facts/, and skills/ directories.
    All operations create checkpoints for rollback capability.

    Args:
        request.instruction: Natural language instruction (e.g., "make my resume emphasize Python")
        request.job_index: Optional job index to scope the operation to a specific application

    Returns:
        AgentResponse with operation result or error
    """
    runner = get_agent_runner()

    try:
        result = await runner.run_async(
            instruction=request.instruction,
            job_index=request.job_index,
            session_id=request.session_id,
        )
        resets_in_s = 0
        if result.circuit_breaker_open:
            cb = get_agent_circuit_breaker()
            status = await cb.get_status()
            resets_in_s = int(status["resets_in_s"])
        return AgentResponse(
            success=result.success,
            response=result.response,
            checkpoint_id=result.checkpoint_id,
            error=result.error,
            circuit_breaker_open=result.circuit_breaker_open,
            iterations_used=result.iterations_used,
            timeout_occurred=result.timeout_occurred,
            resets_in_s=resets_in_s,
        )
    except AgentPathSafetyError as e:
        _logger.warning(f"Agent path safety error: {e}")
        return AgentResponse(
            success=False,
            response="",
            error=f"Operation blocked: {e}",
        )
    except Exception as exc:
        _logger.error(f"Agent error: {exc}")
        return AgentResponse(
            success=False,
            response="",
            error=str(exc),
        )


@app.post("/api/agent/rollback", response_model=RollbackResponse)
async def agent_rollback(request: RollbackRequest) -> RollbackResponse:
    """Rollback to a previous checkpoint.

    Args:
        request.checkpoint_id: ID of the checkpoint to rollback to

    Returns:
        RollbackResponse with success status and original content
    """
    runner = get_agent_runner()

    try:
        content = runner.rollback(request.checkpoint_id)
        return RollbackResponse(
            success=True,
            restored_content=content,
        )
    except FileNotFoundError as e:
        return RollbackResponse(
            success=False,
            error=str(e),
        )
    except Exception as exc:
        _logger.error(f"Rollback error: {exc}")
        return RollbackResponse(
            success=False,
            error=str(exc),
        )


@app.get("/api/agent/checkpoints/{original_path:path}")
async def get_checkpoints(original_path: str) -> dict:
    """Get checkpoints for a file path.

    Args:
        original_path: URL-encoded path to the original file

    Returns:
        List of checkpoint info dicts
    """
    runner = get_agent_runner()
    checkpoints = runner.rollback_store.list_checkpoints(Path(original_path))
    return {
        "checkpoints": [
            {
                "checkpoint_id": c.checkpoint_id,
                "original_path": c.original_path,
                "timestamp": c.timestamp,
            }
            for c in checkpoints
        ]
    }


@app.post("/api/tts")
async def tts(request: TTSRequest) -> Response:
    """Convert text to speech audio. Uses cache when available."""
    cache = get_tts_cache()
    engine = "vibevoice"  # Currently only VibeVoice; will be dynamic with TTSManager

    # Check cache first
    cached_audio = cache.get(request.text, voice=request.voice, engine=engine)
    if cached_audio is not None:
        return Response(
            content=cached_audio,
            media_type="audio/wav",
            headers={
                "Content-Disposition": "inline; filename=speech.wav",
                "X-Cache": "HIT",
            },
        )

    # Cache miss: synthesize
    try:
        audio_bytes = await synthesize_speech(request.text, voice=request.voice)

        # Store in cache (fire-and-forget, don't block response)
        try:
            cache.put(request.text, voice=request.voice, engine=engine, audio_bytes=audio_bytes)
        except Exception as cache_exc:
            _logger.warning(f"Cache put failed: {cache_exc}")

        return Response(
            content=audio_bytes,
            media_type="audio/wav",
            headers={
                "Content-Disposition": "inline; filename=speech.wav",
                "X-Cache": "MISS",
            },
        )
    except Exception as exc:
        _logger.error(f"TTS error: {exc}")
        raise HTTPException(status_code=500, detail=f"TTS synthesis failed: {exc}")


@app.get("/api/tts/cache/stats")
async def tts_cache_stats() -> dict:
    """Return TTS cache statistics."""
    cache = get_tts_cache()
    return cache.stats()


@app.post("/api/voice-clone", response_model=VoiceCloneResponse)
async def voice_clone(request: VoiceCloneRequest) -> VoiceCloneResponse:
    """Upload voice recording for cloning. Accepts multipart WAV audio at 24kHz."""
    # NOTE: For Gradio frontend, the actual file upload is handled via Gradio's
    # gr.Audio component. This endpoint is for programmatic API access.
    raise HTTPException(status_code=501, detail="Use Gradio UI for voice cloning")


@app.post("/api/voice-clone/upload")
async def voice_clone_upload(
    name: str = Form("user_voice"), audio: UploadFile = File(...)
):
    """Upload WAV audio file for voice cloning.

    Accepts 24kHz mono WAV, validates duration 3-10s, applies processing.
    """
    service = get_voice_clone_service()

    # Read audio bytes
    wav_bytes = await audio.read()

    try:
        clone_path = service.process_and_store(wav_bytes, name=name)
        return VoiceCloneResponse(
            success=True,
            name=clone_path.stem,
            message="Voice clone created successfully",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as exc:
        _logger.error(f"Voice clone upload failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Voice cloning failed: {exc}")


@app.get("/api/voices", response_model=VoiceListResponse)
async def list_voices() -> VoiceListResponse:
    """List all available voices (preset + cloned)."""
    voices = []

    # Preset voices from VibeVoice
    try:
        tts = get_tts()
        preset_names = tts.list_voices()
        for name in preset_names:
            voices.append(VoiceInfo(id=name, name=name, type="preset"))
    except Exception as exc:
        _logger.warning(f"Could not list preset voices: {exc}")

    # Cloned voices
    service = get_voice_clone_service()
    for clone in service.list_clones():
        clone_id = f"clone:{clone['name']}"
        voices.append(
            VoiceInfo(
                id=clone_id,
                name=clone["name"],
                type="cloned",
                size_kb=clone["size_kb"],
            )
        )

    return VoiceListResponse(voices=voices)


@app.delete("/api/voice-clone/{name}")
async def delete_voice_clone(name: str):
    """Delete a cloned voice."""
    service = get_voice_clone_service()
    if not service.delete_clone(name):
        raise HTTPException(status_code=404, detail=f"Voice clone '{name}' not found")
    return {"status": "deleted", "name": name}


@app.get("/api/tts/engine/status")
async def tts_engine_status():
    """Return current TTS engine status and VRAM stats."""
    return {
        "state": "preset_only",
        "moss_loaded": False,
        "vram": None,
    }


@app.get("/api/jobs", response_model=JobListResponse)
async def list_jobs() -> JobListResponse:
    """List all available jobs.

    Returns:
        JobListResponse with list of jobs
    """
    jobs = get_job_list()
    return JobListResponse(jobs=[JobInfo(index=idx, name=name) for idx, name in jobs])


@app.get("/api/jobs/{index}/context", response_model=JobContextResponse)
async def get_context(index: int) -> JobContextResponse:
    """Get resume and cover letter context for a job.

    Args:
        index: Job index

    Returns:
        JobContextResponse with resume, cover_letter, and job_name
    """
    bundle_dir = get_bundle_dir(index)
    if bundle_dir is None:
        raise HTTPException(status_code=404, detail=f"Job #{index} not found")

    ctx = get_job_context(index)
    job_name = get_job_name(index)

    return JobContextResponse(
        resume=ctx["resume"],
        cover_letter=ctx["cover_letter"],
        job_name=job_name,
    )


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint.

    Returns:
        HealthResponse with status and vllm_healthy flag
    """
    llm = get_llm()
    vllm_ok = False
    try:
        vllm_ok = await asyncio.wait_for(llm.health(), timeout=5.0)
    except TimeoutError:
        _logger.warning("vLLM health check timed out")
    except Exception as exc:
        _logger.warning(f"vLLM health check failed: {exc}")

    return HealthResponse(status="ok" if vllm_ok else "degraded", vllm_healthy=vllm_ok)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
