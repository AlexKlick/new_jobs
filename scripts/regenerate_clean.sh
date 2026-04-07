#!/bin/bash
# Clean environment regeneration - absolutely no Claude Code variables

cd "$(dirname "$0")"

# Clean environment - remove ALL Claude-related variables
unset CLAUDECODE
unset CLAUDE_CONFIG_HOME
unset CLAUDE_BASE_DIR
unset CLAUDE_INSTANCE_ID

# Check we're really clean
env | grep -i claude && {
    echo "ERROR: Claude environment variables still present!"
    echo "Please run from a fresh terminal that has never had Claude Code loaded."
    exit 1
}

echo "============================================================"
echo " Regenerating Jobs: 5, 7, 35, 37, 39 (Clean Environment)"
echo "============================================================"
echo ""
echo "Environment is clean - no Claude variables detected."
echo ""

# Load only the necessary API keys
if [ -f /home/alexk/documents/agents_sdk/.env ]; then
    # Source .env but filter out Claude-specific variables
    export $(grep -v "^CLAUDE" /home/alexk/documents/agents_sdk/.env | grep -v "^#" | xargs)
fi

# Explicitly set MiniMax credentials
export ANTHROPIC_AUTH_TOKEN="${ANTHROPIC_AUTH_TOKEN_MINIMAX}"
export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL_MINIMAX}"

# Force HOST runtime mode (no Incus containers)
export AGENTS_SDK_RUNTIME=host

# Disable provider wrappers - use base claude command
export AGENTS_SDK_DISABLE_WRAPPERS=1

echo "API Endpoint: $ANTHROPIC_BASE_URL"
echo "Runtime Mode: $AGENTS_SDK_RUNTIME"
echo "Wrappers Disabled: $AGENTS_SDK_DISABLE_WRAPPERS"
echo ""

# Activate venv
source /home/alexk/documents/agents_sdk/.venv/bin/activate

# Run generation
echo "Starting generation..."
python -m agents_sdk.resume_agent.cli resume-batch \
    --workspace . \
    --jobs "5,7,35,37,39" \
    --provider minimax \
    --quality-audit-policy strict

echo ""
echo "============================================================"
echo " Generation complete!"
echo "============================================================"

# Verification
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
echo "Latest output directories:"
ls -dt outputs/*_0{5,7}_* outputs/*_{35,37,39}_* 2>/dev/null | head -10
