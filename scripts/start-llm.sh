#!/bin/bash
# Start vLLM Nanbeige server on GPU 0 (RTX 3090)
# Usage: ./start-llm.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VLLM_DIR="/home/alexk/documents/vllm-nanbeige"

# Activate venv
source "$VLLM_DIR/venv/bin/activate"

# Configuration
MODEL_NAME="${MODEL_NAME:-Nanbeige/Nanbeige4.1-3B}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.80}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-4096}"
MAX_NUM_SEQS="${MAX_NUM_SEQS:-16}"

# Use RTX 3090 (GPU 0)
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES=0

echo "Starting vLLM Nanbeige..."
echo "Model: $MODEL_NAME"
echo "GPU: RTX 3090 (GPU 0)"
echo "Max Model Length: $MAX_MODEL_LEN"
echo "Port: $PORT"

# Check if already running
if curl -s --max-time 5 http://localhost:8000/health > /dev/null 2>&1; then
    echo "vLLM server already running on port $PORT"
    exit 0
fi

# Log file
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/vllm.log"

# Start vLLM
echo "Logging to $LOG_FILE"
vllm serve "$MODEL_NAME" \
    --host "$HOST" \
    --port "$PORT" \
    --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
    --max-model-len "$MAX_MODEL_LEN" \
    --max-num-seqs "$MAX_NUM_SEQS" \
    --trust-remote-code \
    --dtype auto \
    > "$LOG_FILE" 2>&1 &

VLLM_PID=$!
echo "vLLM started with PID: $VLLM_PID"
echo $VLLM_PID > "$SCRIPT_DIR/vllm.pid"

# Wait for server to be ready
echo "Waiting for vLLM to be ready..."
for i in {1..60}; do
    if curl -s --max-time 5 http://localhost:8000/health > /dev/null 2>&1; then
        echo "vLLM server ready on port $PORT"
        exit 0
    fi
    sleep 2
    echo "  ... waiting ($i/60)"
done

echo "WARNING: vLLM may not be fully ready. Check $LOG_FILE"
exit 1
