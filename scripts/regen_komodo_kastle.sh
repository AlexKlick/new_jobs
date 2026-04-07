#!/bin/bash
# Regenerate Komodo Health (job #2) and Kastle (job #33)

set -e

cd "$(dirname "$0")"

# Load environment variables
if [ -f /home/alexk/documents/agents_sdk/.env ]; then
    set -a
    source /home/alexk/documents/agents_sdk/.env
    set +a
fi

echo "============================================================"
echo " Regenerating: Komodo Health (#2) + Kastle (#33)"
echo "============================================================"
echo ""

cat > /tmp/regen_komodo_kastle.py << 'PYEOF'
import asyncio
import os
import sys
from pathlib import Path

# Add agents_sdk to path
sys.path.insert(0, "/home/alexk/documents/agents_sdk")
os.chdir("/home/alexk/documents/new_job_denjobs")

# Load environment
env_path = Path("/home/alexk/documents/agents_sdk/.env")
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k] = v

api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN_MINIMAX", "")
base_url = os.environ.get("ANTHROPIC_BASE_URL_MINIMAX", "")

if not api_key:
    print("ERROR: ANTHROPIC_AUTH_TOKEN_MINIMAX not set")
    sys.exit(1)

print(f"Using base_url: {base_url}")
print(f"API Key: {api_key[:20]}...")
print("")

from agents_sdk.resume_agent.models import BatchGenerationRequest
from agents_sdk.resume_agent.pipeline import run_resume_pipeline_batch

async def main():
    request = BatchGenerationRequest(
        workspace="/home/alexk/documents/new_job_denjobs",
        job_indices=[2, 33],
        provider="minimax",
        fallback_provider=None,
        quality_audit_policy="strict",
        parallel_jobs=1,
    )

    result = await run_resume_pipeline_batch(request)

    print(f"\n{'='*60}")
    print(f" Batch Resume Generation — {result.total_jobs} jobs")
    print(f"{'='*60}")

    for job_result in result.job_results:
        status = "SUCCESS" if job_result.result.success else "FAILED"
        print(f"  [{status}] Job {job_result.job_index}: {job_result.company}")
        if not job_result.result.success:
            for err in (job_result.result.errors or []):
                print(f"       Error: {err}")

    print(f"\n  Succeeded: {result.succeeded}/{result.total_jobs}")
    print(f"  Failed:    {result.failed}/{result.total_jobs}")

    return result.failed == 0

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
PYEOF

# Run the Python script
/home/alexk/documents/agents_sdk/.venv/bin/python /tmp/regen_komodo_kastle.py
