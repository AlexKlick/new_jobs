"""
Agent Runner - Claude Code CLI Subprocess Management

Provides natural language file operations via Claude CLI with:
- Directory sandboxing (--add-dir flags)
- Tool allowlisting (Edit, Read, Glob, Grep only)
- Path validation before operations
- Timeout enforcement

Usage:
    runner = AgentRunner(allowed_dirs=[...], checkpoint_dir=Path(...))
    result = runner.run("make my resume emphasize Python")
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import re
from uuid import UUID

from agent.circuit_breaker import AgentCircuitBreaker, CircuitBreakerOpenError
from agent.rollback_store import CheckpointInfo, RollbackStore

_logger = logging.getLogger(__name__)

# Global circuit breaker instance for escalation loop protection
_agent_circuit_breaker: AgentCircuitBreaker | None = None


def get_agent_circuit_breaker() -> AgentCircuitBreaker:
    """Get or create the global agent circuit breaker."""
    global _agent_circuit_breaker
    if _agent_circuit_breaker is None:
        _agent_circuit_breaker = AgentCircuitBreaker(threshold=3, window_s=300)
    return _agent_circuit_breaker

# Configuration
DEFAULT_TIMEOUT_S = 120  # 2 minutes
DEFAULT_MAX_ITERATIONS = 5
CLAUDE_CLI_PATH = "/home/alexk/.local/bin/claude"

# Allowed tools - deny Bash/WebSearch and keep file mutation scoped.
ALLOWED_TOOLS = ["Edit", "Read", "Glob", "Grep"]

# Forbidden path patterns - block traversal and sensitive files.
FORBIDDEN_PATTERNS = ["..", ".env", ".aws", ".ssh", ".git", ".npmrc", ".pypirc"]
PATH_TOKEN_RE = re.compile(r"(?P<path>(?:`[^`]+`)|(?:\"[^\"]+\")|(?:'[^']+')|(?:/?[\w./-]+\.[\w.-]+)|(?:/?[\w.-]+/[\w./-]+))")


class AgentPathSafetyError(ValueError):
    """Raised when a path is outside allowed directories or uses forbidden patterns."""
    pass


class AgentTimeoutError(Exception):
    """Raised when agent exceeds configured timeout."""
    pass


class AgentError(Exception):
    """Raised when Claude CLI returns non-zero exit code."""
    pass


class AgentIterationLimitError(Exception):
    """Raised when agent exceeds maximum iterations."""
    pass


@dataclass
class AgentResult:
    """Result of an agent operation."""
    success: bool
    response: str
    checkpoint_id: str | None = None
    error: str | None = None
    circuit_breaker_open: bool = False
    iterations_used: int = 0
    timeout_occurred: bool = False


def validate_path_for_agent(path_str: str, allowed_dirs: list[Path]) -> bool:
    """Validate that a path is within allowed directories.

    Args:
        path_str: Path string to validate
        allowed_dirs: List of allowed directory paths

    Returns:
        True if path is safe, False otherwise
    """
    # Check for forbidden patterns first
    for pattern in FORBIDDEN_PATTERNS:
        if pattern in path_str:
            return False

    try:
        path = Path(path_str)
        if path.is_absolute():
            abs_path = path.resolve()
            return any(abs_path.is_relative_to(allowed_dir.resolve()) for allowed_dir in allowed_dirs)

        for allowed_dir in allowed_dirs:
            abs_allowed = allowed_dir.resolve()
            candidate_roots = [abs_allowed]
            if abs_allowed.parent not in candidate_roots:
                candidate_roots.append(abs_allowed.parent)
            if abs_allowed.parent.parent not in candidate_roots:
                candidate_roots.append(abs_allowed.parent.parent)

            for root in candidate_roots:
                candidate = (root / path).resolve()
                if candidate.is_relative_to(abs_allowed):
                    return True
        return False
    except Exception:
        return False


def _extract_instruction_paths(instruction: str) -> list[str]:
    """Extract explicit path-like tokens from a natural-language instruction."""
    paths: list[str] = []
    for match in PATH_TOKEN_RE.finditer(instruction):
        candidate = match.group("path").strip("`'\"")
        if "/" in candidate or candidate.startswith(".") or "." in Path(candidate).name:
            paths.append(candidate)
    return paths


def validate_instruction_for_agent(instruction: str, allowed_dirs: list[Path]) -> None:
    """Reject instructions that explicitly reference unsafe paths."""
    for candidate in _extract_instruction_paths(instruction):
        if not validate_path_for_agent(candidate, allowed_dirs):
            raise AgentPathSafetyError(f"Unsafe path reference blocked: {candidate}")


def resolve_job_bundle_dir(project_root: Path, job_index: int) -> Path | None:
    """Resolve a job bundle under applications/all_jobs/ by numeric prefix."""
    all_jobs_dir = project_root / "applications" / "all_jobs"
    if not all_jobs_dir.exists():
        return None
    prefix = f"{job_index:02d}_"
    for entry in sorted(all_jobs_dir.iterdir()):
        if entry.is_dir() and entry.name.startswith(prefix):
            return entry.resolve()
    return None


def _normalize_session_id(session_id: str | None) -> str | None:
    """Return a valid UUID session id for Claude CLI, or None."""
    if not session_id:
        return None
    try:
        return str(UUID(str(session_id)))
    except (ValueError, TypeError):
        return None


def build_claude_command(
    instruction: str,
    allowed_dirs: list[Path],
    tools: list[str] | None = None,
    session_id: str | None = None,
) -> list[str]:
    """Build claude CLI command with sandbox flags.

    Args:
        instruction: Natural language instruction
        allowed_dirs: Directories to allow tool access
        tools: List of allowed tools (default: ALLOWED_TOOLS)

    Returns:
        Command list for subprocess.run
    """
    if tools is None:
        tools = ALLOWED_TOOLS

    cmd = [
        CLAUDE_CLI_PATH,
        "-p",
        "--output-format", "text",
        "--permission-mode", "acceptEdits",
    ]

    cmd.extend(["--allowedTools", ",".join(tools)])

    normalized_session_id = _normalize_session_id(session_id)
    if normalized_session_id:
        cmd.extend(["--session-id", normalized_session_id])

    for d in allowed_dirs:
        cmd.extend(["--add-dir", str(d.resolve())])

    cmd.extend(["--", instruction])

    return cmd


def run_claude_agent(
    instruction: str,
    allowed_dirs: list[Path],
    timeout_s: int = DEFAULT_TIMEOUT_S,
    cwd: Path | None = None,
    session_id: str | None = None,
) -> str:
    """Run Claude CLI with sandboxing and timeout.

    Args:
        instruction: Natural language instruction
        allowed_dirs: Directories to allow tool access
        timeout_s: Maximum execution time in seconds
        cwd: Working directory for subprocess

    Returns:
        Claude CLI stdout response

    Raises:
        AgentPathSafetyError: If instruction contains path traversal attempts
        AgentTimeoutError: If execution exceeds timeout
        AgentError: If Claude CLI returns non-zero exit
    """
    # Build command
    validate_instruction_for_agent(instruction, allowed_dirs)
    cmd = build_claude_command(instruction, allowed_dirs, session_id=session_id)

    # Set working directory
    work_dir = str(cwd or allowed_dirs[0].resolve())

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=work_dir,
        )

        if result.returncode != 0:
            raise AgentError(f"Claude CLI error: {result.stderr}")

        return result.stdout

    except subprocess.TimeoutExpired as e:
        raise AgentTimeoutError(f"Agent exceeded {timeout_s}s timeout") from e
    except FileNotFoundError as e:
        raise AgentError(f"Claude CLI not found at {CLAUDE_CLI_PATH}") from e


class AgentRunner:
    """Manages Claude CLI agent operations with sandbox and rollback support."""

    def __init__(
        self,
        project_root: Path,
        allowed_dirs: list[Path] | None = None,
        checkpoint_dir: Path | None = None,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
    ):
        """Initialize AgentRunner.

        Args:
            project_root: Root directory of the project
            allowed_dirs: Directories to allow tool access (default: applications/, facts/, skills/)
            checkpoint_dir: Directory for rollback checkpoints
            timeout_s: Maximum execution time per operation
            max_iterations: Maximum iterations per request
        """
        self.project_root = project_root
        self.timeout_s = timeout_s
        self.max_iterations = max_iterations

        # Default allowed dirs if not specified
        if allowed_dirs is None:
            allowed_dirs = [
                project_root / "applications" / "all_jobs",
                project_root / "facts",
                project_root / "skills",
            ]
        self.allowed_dirs = allowed_dirs

        # Checkpoint directory for rollback
        if checkpoint_dir is None:
            checkpoint_dir = project_root / ".agent_checkpoints"
        self.checkpoint_dir = checkpoint_dir
        self.checkpoint_dir.mkdir(exist_ok=True)
        self.rollback_store = RollbackStore(checkpoint_dir=self.checkpoint_dir)

    def get_allowed_dirs(self, job_index: int | None = None) -> list[Path]:
        """Resolve the directory scope for an agent request."""
        if job_index is not None:
            bundle_dir = resolve_job_bundle_dir(self.project_root, job_index)
            if bundle_dir is not None:
                return [bundle_dir]
        return [path.resolve() for path in self.allowed_dirs]

    def run(
        self,
        instruction: str,
        job_index: int | None = None,
        max_iterations: int | None = None,
        session_id: str | None = None,
    ) -> AgentResult:
        """Run agent with sandboxing, timeout, and iteration limit.

        Args:
            instruction: Natural language instruction
            job_index: Optional job index to scope to specific application
            max_iterations: Maximum Claude CLI iterations (default: self.max_iterations)

        Returns:
            AgentResult with response and checkpoint info

        Raises:
            AgentPathSafetyError: If instruction contains unsafe paths
            AgentTimeoutError: If execution exceeds timeout
            AgentError: If Claude CLI fails
        """
        allowed = self.get_allowed_dirs(job_index)
        checkpoint_id = self.rollback_store.create_run_checkpoint(allowed)

        try:
            response = run_claude_agent(
                instruction=instruction,
                allowed_dirs=allowed,
                timeout_s=self.timeout_s,
                cwd=self.project_root,
                session_id=session_id,
            )
            return AgentResult(
                success=True,
                response=response,
                checkpoint_id=checkpoint_id,
                iterations_used=1,
            )
        except AgentTimeoutError as exc:
            return AgentResult(
                success=False,
                response="",
                error=str(exc),
                checkpoint_id=checkpoint_id,
                iterations_used=1,
                timeout_occurred=True,
            )
        except (AgentError, AgentPathSafetyError) as exc:
            return AgentResult(
                success=False,
                response="",
                error=str(exc),
                checkpoint_id=checkpoint_id,
                iterations_used=1,
            )

    def rollback(self, checkpoint_id: str) -> str | None:
        """Rollback to a specific checkpoint.

        Args:
            checkpoint_id: ID of the checkpoint to rollback to

        Returns:
            Original file content, or None if not found
        """
        return self.rollback_store.rollback(checkpoint_id)

    def get_latest_checkpoint(self, file_path: Path) -> CheckpointInfo | None:
        """Get the most recent checkpoint for a file.

        Args:
            file_path: Path to the file

        Returns:
            CheckpointInfo or None
        """
        return self.rollback_store.get_latest_checkpoint(file_path)

    async def run_async(
        self,
        instruction: str,
        job_index: int | None = None,
        session_id: str | None = None,
    ) -> AgentResult:
        """Async version of run() using thread pool executor.

        Args:
            instruction: Natural language instruction
            job_index: Optional job index to scope to specific application

        Returns:
            AgentResult with response and checkpoint info
        """
        # Check circuit breaker first
        cb = get_agent_circuit_breaker()
        if await cb.is_open():
            status = await cb.get_status()
            return AgentResult(
                success=False,
                response="",
                error=f"Circuit breaker open. Too many escalation attempts. Please wait {int(status['resets_in_s'])} seconds.",
                circuit_breaker_open=True,
            )

        # Check for escalation keywords in instruction
        escalation_keywords = ["escalate", "ask another", "consult", "forward to", "handoff"]
        if any(kw in instruction.lower() for kw in escalation_keywords):
            escalation_session_id = session_id or f"session_{id(self)}"
            await cb.record_escalation(escalation_session_id)
            if await cb.is_open():
                status = await cb.get_status()
                return AgentResult(
                    success=False,
                    response="",
                    error=f"Circuit breaker opened. Too many escalation attempts. Please wait {int(status['resets_in_s'])} seconds.",
                    circuit_breaker_open=True,
                )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            ThreadPoolExecutor(),
            self.run,
            instruction,
            job_index,
            None,
            session_id,
        )
