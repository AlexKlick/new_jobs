#!/bin/bash
# Regenerate jobs 5, 7, 35, 37, 39 with fixed external evaluation
# Run this script OUTSIDE of Claude Code session

cd "$(dirname "$0")"

# Ensure we're not in a nested Claude Code session
if [ -n "$CLAUDECODE" ]; then
    echo "ERROR: This script must be run outside of Claude Code session."
    echo "Unset CLAUDECODE or run in a fresh terminal."
    exit 1
fi

# Activate virtual environment
source /home/alexk/documents/agents_sdk/.venv/bin/activate

# Use host runtime mode to avoid CLI conflicts
export AGENTS_SDK_RUNTIME=host

echo "============================================================"
echo " Regenerating Jobs: 5, 7, 35, 37, 39"
echo "============================================================"
echo ""
echo "NOTE: This will take 20-30 minutes. Please be patient."
echo "Each job requires LLM generation + external evaluation."
echo ""
echo "Progress will be shown below..."
echo "============================================================"
echo ""

# Run batch generation
python -m agents_sdk.resume_agent.cli resume-batch \
    --workspace . \
    --jobs "5,7,35,37,39" \
    --provider minimax \
    --quality-audit-policy strict

echo ""
echo "============================================================"
echo " Generation complete!"
echo "============================================================"

# Verify all 40 jobs have PDFs
echo ""
echo "Verifying PDFs..."
missing=0
for i in {1..40}; do
    pdf_count=$(find outputs -name "*_${i#}_*" -name "*.pdf" 2>/dev/null | wc -l)
    if [ "$pdf_count" -lt 2 ]; then
        echo "  Job $i: MISSING PDFs"
        missing=$((missing + 1))
    fi
done

if [ $missing -eq 0 ]; then
    echo "  ✓ All 40 jobs have PDFs!"
else
    echo "  ✗ $missing jobs are missing PDFs"
fi

echo ""
echo "Output directories:"
ls -dt outputs/*_0{5,7}_* outputs/*_{35,37,39}_* 2>/dev/null | head -20
