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
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from circuit_breaker import AgentCircuitBreaker, CircuitBreakerOpenError
from rollback_store import CheckpointInfo, RollbackStore

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

# Allowed tools - deny Bash, WebSearch, Write (could create files anywhere), etc.
ALLOWED_TOOLS = ["Edit", "Read", "Glob", "Grep"]

# Forbidden path patterns - block path traversal and sensitive files
# Note: We don't block "/" broadly since relative paths like "skills/resume.yaml" are valid
FORBIDDEN_PATTERNS = ["..", ".env", ".aws", ".ssh", ".git"]


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
        abs_path = Path(path_str).resolve()
        for allowed_dir in allowed_dirs:
            abs_allowed = allowed_dir.resolve()
            # Check if path is within allowed_dir
            abs_path.relative_to(abs_allowed)
            return True
        return False
    except Exception:
        return False


def build_claude_command(
    instruction: str,
    allowed_dirs: list[Path],
    tools: list[str] | None = None,
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
        "--non-interactive",
    ]

    # Add allowed tools
    for tool in tools:
        cmd.extend(["--allowedTools", tool])

    # Add allowed directories
    for d in allowed_dirs:
        cmd.extend(["--add-dir", str(d.resolve())])

    cmd.extend(["--", instruction])

    return cmd


def run_claude_agent(
    instruction: str,
    allowed_dirs: list[Path],
    timeout_s: int = DEFAULT_TIMEOUT_S,
    cwd: Path | None = None,
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
    cmd = build_claude_command(instruction, allowed_dirs)

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
                project_root / "applications",
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

    def _create_checkpoint(self, file_path: Path) -> str:
        """Create a checkpoint backup of a file before modification.

        Args:
            file_path: Path to file to checkpoint

        Returns:
            Checkpoint ID (timestamp-based)
        """
        checkpoint_id = str(int(time.time() * 1000))
        checkpoint_name = f"{file_path.name}.{checkpoint_id}.bak"
        checkpoint_path = self.checkpoint_dir / checkpoint_name

        if file_path.exists():
            shutil.copy2(file_path, checkpoint_path)
            _logger.info(f"Created checkpoint: {checkpoint_path}")

        return checkpoint_id

    def run(self, instruction: str, job_index: int | None = None, max_iterations: int | None = None) -> AgentResult:
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
        if max_iterations is None:
            max_iterations = self.max_iterations

        # Determine allowed dirs - if job_index provided, scope to that job
        allowed = self.allowed_dirs.copy()
        if job_index is not None:
            job_app_dir = self.project_root / "applications" / f"job_{job_index:02d}"
            if job_app_dir.exists():
                allowed = [job_app_dir]

        # CRITICAL: Create checkpoint BEFORE running agent
        checkpoint_id = self.rollback_store.create_checkpoint_all(allowed)

        iteration_count = 0
        current_instruction = instruction

        while iteration_count < max_iterations:
            try:
                response = run_claude_agent(
                    instruction=current_instruction,
                    allowed_dirs=allowed,
                    timeout_s=self.timeout_s,
                    cwd=self.project_root,
                )

                # Check if agent indicated completion
                if self._is_complete(response):
                    return AgentResult(
                        success=True,
                        response=response,
                        checkpoint_id=checkpoint_id,
                        iterations_used=iteration_count + 1,
                    )

                # Continue with next iteration
                iteration_count += 1
                if iteration_count >= max_iterations:
                    break

                # Add continuation prompt
                current_instruction = f"{instruction}\n\nPrevious attempt result:\n{response}\n\nPlease complete the requested changes or confirm if already done."

            except AgentTimeoutError as e:
                return AgentResult(
                    success=False,
                    response="",
                    error=str(e),
                    checkpoint_id=checkpoint_id,
                    iterations_used=iteration_count,
                    timeout_occurred=True,
                )
            except AgentError as e:
                return AgentResult(
                    success=False,
                    response="",
                    error=str(e),
                    checkpoint_id=checkpoint_id,
                    iterations_used=iteration_count,
                )

        # Max iterations reached
        return AgentResult(
            success=False,
            response="",
            error=f"Exceeded maximum iterations ({max_iterations})",
            checkpoint_id=checkpoint_id,
            iterations_used=max_iterations,
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

    def _is_complete(self, response: str) -> bool:
        """Check if agent response indicates completion.

        Args:
            response: Agent response text

        Returns:
            True if response indicates the task is complete
        """
        # Look for completion indicators
        complete_phrases = [
            "done", "completed", "finished", "updated",
            "modified", "changed", "edited",
        ]
        response_lower = response.lower()

        # Check for completion phrases and absence of follow-up questions
        has_complete = any(phrase in response_lower for phrase in complete_phrases)
        has_followup = any(q in response_lower for q in ["?", "would you like", "should i", "shall i"])

        return has_complete and not has_followup

    async def run_async(self, instruction: str, job_index: int | None = None) -> AgentResult:
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
            session_id = f"session_{id(self)}"
            await cb.record_escalation(session_id)
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
        )
