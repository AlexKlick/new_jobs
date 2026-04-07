#!/bin/bash
# Regenerate all markdown-only jobs: 5,7,8,9,10-14,16-31,35,37,39

set -e

cd "$(dirname "$0")"

# Load environment variables
if [ -f /home/alexk/documents/agents_sdk/.env ]; then
    set -a
    source /home/alexk/documents/agents_sdk/.env
    set +a
fi

echo "============================================================"
echo " Regenerating 28 pending jobs (markdown -> PDF)"
echo "============================================================"
echo ""

cat > /tmp/regen_pending.py << 'PYEOF'
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, "/home/alexk/documents/agents_sdk")
os.chdir("/home/alexk/documents/new_job_denjobs")

env_path = Path("/home/alexk/documents/agents_sdk/.env")
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k] = v

from agents_sdk.resume_agent.models import BatchGenerationRequest
from agents_sdk.resume_agent.pipeline import run_resume_pipeline_batch

async def main():
    pending = [5,7,8,9,10,11,12,13,14,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,35,37,39]
    print(f"Jobs to process: {pending}")
    print(f"Total: {len(pending)} jobs")
    print("")

    request = BatchGenerationRequest(
        workspace="/home/alexk/documents/new_job_denjobs",
        job_indices=pending,
        provider="minimax",
        fallback_provider=None,
        quality_audit_policy="strict",
        parallel_jobs=1,
    )

    result = await run_resume_pipeline_batch(request)

    print(f"\n{'='*60}")
    print(f" Results: {result.succeeded}/{result.total_jobs} succeeded")
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

/home/alexk/documents/agents_sdk/.venv/bin/python /tmp/regen_pending.py
