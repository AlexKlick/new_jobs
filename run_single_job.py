#!/usr/bin/env python3
"""
Single-job runner — called by regen_multi_provider.py in a subprocess.
Usage: python3 run_single_job.py <job_index> <provider> 2>&1
Exit 0 = success, non-zero = failure.
"""
import asyncio, json, os, shutil, sys
import fcntl
from pathlib import Path

AGENTS_SDK_ROOT = "/home/alexk/documents/agents_sdk"
sys.path.insert(0, AGENTS_SDK_ROOT)
os.chdir("/home/alexk/documents/new_job_denjobs")

for _env_path in [
    Path(AGENTS_SDK_ROOT) / ".env",
    Path("/media/alexk/RAID5_Storage/alexk_home/Desktop/.claude/.env"),
    Path.home() / ".claude" / ".env",
]:
    if _env_path.exists():
        with open(_env_path) as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _, _v = _line.partition("=")
                    _k, _v = _k.strip(), _v.strip().strip("'").strip('"')
                    if _k and _k not in os.environ:
                        os.environ[_k] = _v


def _find_claude_source_dir() -> Path:
    candidates = [
        Path(os.environ.get("AGENTS_SDK_CLAUDE_DIR", "")).expanduser(),
        Path("/home/alexk/.claude"),
        Path("/media/alexk/RAID5_Storage/alexk_home/Desktop/.claude"),
        Path.home() / ".claude",
    ]
    for candidate in candidates:
        if not str(candidate):
            continue
        if (candidate / "router" / "instance_manager.py").exists() and (candidate / "scripts").exists():
            return candidate.resolve()
    raise FileNotFoundError("Unable to locate a Claude runtime with router and scripts")


def _prepare_writable_claude_runtime() -> Path:
    source = _find_claude_source_dir()
    runtime_root = Path("/tmp/claude-runtime").resolve()
    lock_path = Path("/tmp/claude-runtime.lock")

    runtime_root.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            shutil.copytree(source / "router", runtime_root / "router", dirs_exist_ok=True)
            shutil.copytree(source / "scripts", runtime_root / "scripts", dirs_exist_ok=True)
            for name in [".env", "profiles.json", "settings.json", "settings.local.json"]:
                src = source / name
                if src.exists():
                    shutil.copy2(src, runtime_root / name)
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    os.environ["AGENTS_SDK_CLAUDE_DIR"] = str(runtime_root)
    os.environ["AGENTS_SDK_ENV_FILE"] = str(runtime_root / ".env")
    os.environ["AGENTS_SDK_PROVIDER_CLI_MINIMAX"] = str(runtime_root / "scripts" / "claude-minimax")
    os.environ["AGENTS_SDK_PROVIDER_CLI_ZAI"] = str(runtime_root / "scripts" / "claude-zai")
    os.environ["AGENTS_SDK_PROVIDER_CLI_ANTHROPIC_PRO"] = str(runtime_root / "scripts" / "claude-anthropic-pro")
    os.environ["CLAUDE_BASE_DIR"] = str(runtime_root)
    return runtime_root


_prepare_writable_claude_runtime()

from agents_sdk.resume_agent.models import GenerationRequest
from agents_sdk.resume_agent.pipeline import run_resume_pipeline
from agents_sdk.resume_agent.unified_workspace import promote_latest_application_for_job


async def main():
    if len(sys.argv) < 3:
        print("Usage: run_single_job.py <job_index> <provider>", file=sys.stderr)
        sys.exit(2)

    job_index = int(sys.argv[1])
    provider  = sys.argv[2]

    request = GenerationRequest(
        workspace="/home/alexk/documents/new_job_denjobs",
        job_index=job_index,
        provider=provider,
        fallback_provider=None,
        quality_audit_policy="advisory",
    )

    print(f"[run_single_job] job={job_index} provider={provider}", flush=True)
    result = await run_resume_pipeline(request)

    if result.success:
        try:
            promote_latest_application_for_job(
                "/home/alexk/documents/new_job_denjobs",
                job_index,
                extra_workspaces=["/home/alexk/documents/new_job"],
            )
        except Exception as exc:
            print(f"[run_single_job] WARN promote_failed job={job_index}: {exc}", flush=True)
        print(f"[run_single_job] SUCCESS job={job_index} run_dir={result.run_dir}", flush=True)
        sys.exit(0)
    else:
        errs = "; ".join(result.errors or ["unknown"])
        print(f"[run_single_job] FAILED job={job_index}: {errs}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
