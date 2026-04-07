#!/bin/bash
# Direct API regeneration - bypasses CLI wrappers

set -e

cd "$(dirname "$0")"

# Load environment variables
if [ -f /home/alexk/documents/agents_sdk/.env ]; then
    set -a
    source /home/alexk/documents/agents_sdk/.env
    set +a
fi

echo "============================================================"
echo " Regenerating Jobs: 5, 7, 35, 37, 39 (Direct API)"
echo "============================================================"
echo ""
echo "Using direct Anthropic SDK calls to MiniMax endpoint..."
echo ""

# Create Python script for direct generation
cat > /tmp/regenerate_jobs.py << 'PYTHON_SCRIPT'
import asyncio
import os
import sys
from pathlib import Path

# Add agents_sdk to path
sys.path.insert(0, "/home/alexk/documents/agents_sdk")

from anthropic import Anthropic
from resume_agent.models import BatchGenerationRequest
from resume_agent.pipeline import run_resume_pipeline_batch

# Configure Anthropic client with MiniMax endpoint
api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN_MINIMAX", "")
base_url = os.environ.get("ANTHROPIC_BASE_URL_MINIMAX", "")

if not api_key:
    print("ERROR: ANTHROPIC_AUTH_TOKEN_MINIMAX not set")
    sys.exit(1)

print(f"Using base_url: {base_url}")
print(f"API Key: {api_key[:20]}...")
print("")

async def main():
    request = BatchGenerationRequest(
        workspace="/home/alexk/documents/new_job_denjobs",
        job_indices=[5, 7, 35, 37, 39],
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
        status = "✓" if job_result.result.success else "✗"
        print(f"  {status} Job {job_result.job_index}: {job_result.company}")

    print(f"\n  Succeeded: {result.succeeded}/{result.total_jobs}")
    print(f"  Failed:    {result.failed}/{result.total_jobs}")

    if result.errors:
        print("\nErrors:")
        for error in result.errors:
            print(f"  - {error}")

    return result.failed == 0

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
PYTHON_SCRIPT

# Run the Python script
/home/alexk/documents/agents_sdk/.venv/bin/python /tmp/regenerate_jobs.py

echo ""
echo "============================================================"
echo " Verification: Checking PDFs for all 40 jobs"
echo "============================================================"

missing=0
for i in {1..40}; do
    pdf_count=$(find outputs -name "*_${i#}_*" -name "*.pdf" 2>/dev/null | wc -l)
    if [ "$pdf_count" -lt 2 ]; then
        echo "  Job $i: MISSING PDFs (found $pdf_count, expected 2)"
        missing=$((missing + 1))
    fi
done

if [ $missing -eq 0 ]; then
    echo "  ✓ All 40 jobs have PDFs!"
else
    echo "  ✗ $missing jobs are missing PDFs"
fi
